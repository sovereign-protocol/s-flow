from __future__ import annotations

from collections import Counter
from typing import Any

from .model import (
    ArtifactRevision,
    ArtifactState,
    DefinitionError,
    Operation,
    PersonalProjection,
    Predicate,
    ProcessPosition,
    QueueState,
    TaskActionError,
    UserTask,
    WorkItem,
    WorkflowDefinition,
    WorkflowInstance,
)
from .schema_validation import validate_response


class WorkflowEngine:
    def __init__(
        self,
        definition: WorkflowDefinition,
        *,
        predicates: dict[str, Predicate] | None = None,
        operations: dict[str, Operation] | None = None,
    ) -> None:
        self.definition = definition
        self.predicates = predicates or {}
        self.operations = operations or {}

    def create_instance(
        self,
        instance_id: str,
        role_assignments: dict[str, list[str]],
        *,
        data: dict[str, Any] | None = None,
    ) -> WorkflowInstance:
        self._validate_role_assignments(role_assignments)
        artifacts = {
            artifact_id: ArtifactState(id=artifact_id)
            for artifact_id in self.definition.artifacts
        }
        instance = WorkflowInstance(
            id=instance_id,
            definition=self.definition,
            role_assignments={
                role: list(dict.fromkeys(users))
                for role, users in role_assignments.items()
            },
            artifacts=artifacts,
            data=dict(data or {}),
        )
        instance.emit("instanceCreated", "Workflow instance created.")
        return instance

    def start(self, instance: WorkflowInstance) -> None:
        if instance.status != "created":
            raise TaskActionError("Only a created instance can be started.")
        instance.status = "active"
        start_id = self.definition.starts_by_container[self.definition.id]
        self._enter(instance, start_id)

    def submit(
        self,
        instance: WorkflowInstance,
        user_id: str,
        task_id: str,
        response: dict[str, Any],
    ) -> None:
        task = instance.tasks.get(task_id)
        if task is None:
            raise TaskActionError(f"Unknown task {task_id}.")
        if task.user_id != user_id:
            raise TaskActionError("Task is assigned to another user.")
        if task.status != "open":
            raise TaskActionError(f"Task {task_id} is not open.")

        self._validate_task_semantics(instance, task, response)
        validate_response(self.definition, task.schema_ref, response)

        task.response = dict(response)
        task.status = "completed"
        instance.node_outputs.setdefault(task.node_id, []).append(
            {
                "visit": task.visit,
                "userId": user_id,
                "taskId": task.id,
                "kind": task.kind,
                "response": dict(response),
                "metadata": dict(task.metadata),
            }
        )
        instance.data["lastHumanResponse"] = dict(response)
        instance.data["lastHumanActor"] = user_id
        instance.recent_activity = f"{user_id} completed {self.definition.nodes[task.node_id].name}"
        instance.emit(
            "taskCompleted",
            instance.recent_activity,
            task.node_id,
            userId=user_id,
            taskId=task.id,
        )

        if task.kind == "interactionCreator":
            self._handle_question_creator_response(instance, task, response)
        elif task.kind == "interactionResponder":
            self._handle_question_response(instance, task, response)
        elif task.kind == "applicability":
            self._handle_applicability_response(instance, task, response)

        self._unlock_next_sequential_task(instance, task.node_id, task.visit)

        if self._node_is_complete(instance, task.node_id, task.visit):
            self._complete_human_node(instance, task.node_id, task.visit)

    def position(self, instance: WorkflowInstance) -> ProcessPosition:
        last = None
        if instance.last_completed_stage_id:
            node = self.definition.nodes[instance.last_completed_stage_id]
            last = {"id": node.id, "name": node.name}

        current: list[dict[str, Any]] = []
        current_stage_id = self._current_major_stage_id(instance)
        if current_stage_id:
            node = self.definition.nodes[current_stage_id]
            current.append({"id": node.id, "name": node.name})

        return ProcessPosition(
            last_completed_stage=last,
            current_stages=current,
            recent_activity=instance.recent_activity,
        )

    def personal_projection(
        self,
        instance: WorkflowInstance,
        user_id: str,
    ) -> PersonalProjection:
        open_tasks = [
            task
            for task in instance.tasks.values()
            if task.user_id == user_id and task.status == "open"
        ]
        open_tasks.sort(key=lambda task: task.id)
        task_payloads = [
            {
                "id": task.id,
                "nodeId": task.node_id,
                "label": self.definition.nodes[task.node_id].name,
                "kind": task.kind,
                "metadata": dict(task.metadata),
            }
            for task in open_tasks
        ]

        cursor = instance.information_cursor.get(user_id, 0)
        information = [
            {
                "sequence": event.sequence,
                "type": event.type,
                "message": event.message,
                "data": dict(event.data),
            }
            for event in instance.events
            if event.sequence > cursor
            and event.type in {"artifact", "information", "outcome"}
        ]

        waiting_reason = None
        if not open_tasks and instance.status == "active":
            waiting_reason = self._waiting_reason(instance, user_id)

        if open_tasks:
            primary = "inputRequired"
        elif information:
            primary = "information"
        else:
            primary = "waiting"

        return PersonalProjection(
            primary_state=primary,
            tasks=task_payloads,
            waiting_reason=waiting_reason,
            information_items=information,
        )

    def acknowledge_information(self, instance: WorkflowInstance, user_id: str) -> None:
        instance.information_cursor[user_id] = len(instance.events)

    def post_message(
        self,
        instance: WorkflowInstance,
        user_id: str,
        message: str,
    ) -> dict[str, Any]:
        if not message.strip():
            raise TaskActionError("Discussion messages cannot be empty.")
        node_id = instance.current_node_id
        if not node_id:
            raise TaskActionError("No workflow activity is active.")
        node = self.definition.nodes[node_id]
        interaction = node.extension("controlledInteraction")
        if not interaction or interaction.get("kind") not in {
            "discussion",
            "restrictedTest",
        }:
            raise TaskActionError("The current activity has no open discussion.")

        permitted: set[str] = set()
        for role in interaction.get("creators", "").split():
            permitted.update(instance.role_users(role))
        if user_id not in permitted:
            raise TaskActionError("The user may not contribute to this discussion.")

        item = instance.current_work_item()
        context_id = item.id if item else f"{node_id}:{instance.node_visits.get(node_id, 0)}"
        discussions = instance.data.setdefault("discussions", {})
        thread = discussions.setdefault(context_id, [])
        record = {
            "sequence": len(thread) + 1,
            "authorId": user_id,
            "message": message,
            "nodeId": node_id,
            "workItemId": item.id if item else None,
        }
        thread.append(record)
        instance.emit(
            "information",
            f"{user_id} contributed to {node.name}.",
            node_id,
            discussionContextId=context_id,
            messageSequence=record["sequence"],
        )
        return dict(record)

    def invoke_global_action(
        self,
        instance: WorkflowInstance,
        user_id: str,
        action_name: str,
        *,
        artifact_id: str,
        reason: str | None = None,
    ) -> None:
        profile = self.definition.process_extensions["profile"][0]
        actions = [
            child
            for child in profile.get("_children", [])
            if child.get("_name") == "globalAction"
            and child.get("action") == action_name
            and child.get("artifactRef") == artifact_id
        ]
        if len(actions) != 1:
            raise TaskActionError("The requested global action is not available.")
        action = actions[0]
        if user_id not in instance.role_users(action["actorRole"]):
            raise TaskActionError("The user is not authorized for this global action.")
        artifact = instance.artifacts[artifact_id]
        if artifact.lifecycle_state not in action["allowedStates"].split():
            raise TaskActionError(
                f"Action {action_name} is unavailable while {artifact_id} is "
                f"{artifact.lifecycle_state}."
            )
        if action_name != "withdraw":
            raise TaskActionError(f"Unsupported global action {action_name}.")

        artifact.lifecycle_state = "withdrawn"
        instance.status = "completed"
        instance.outcome = action["outcome"]
        instance.emit(
            "artifact",
            f"Withdrew {artifact_id}.",
            instance.current_node_id,
            artifactId=artifact_id,
            revisionId=artifact.current_revision_id,
            reason=reason,
        )
        instance.emit(
            "outcome",
            f"Workflow ended: {instance.outcome}.",
            instance.current_node_id,
            outcome=instance.outcome,
        )

    def confirm_candidate_eligibility(
        self,
        instance: WorkflowInstance,
        facilitator_user_id: str,
        candidate_id: str,
    ) -> None:
        if instance.data.get("eligibilityMode") != "open":
            raise TaskActionError("Runtime candidate confirmation is only used in open mode.")
        if facilitator_user_id not in instance.role_users("facilitator"):
            raise TaskActionError("Only the facilitator may confirm candidate eligibility.")
        eligible = instance.data.setdefault("eligibleCandidates", [])
        if candidate_id not in eligible:
            eligible.append(candidate_id)
            instance.emit(
                "information",
                f"Candidate eligibility confirmed: {candidate_id}.",
                instance.current_node_id,
                candidateId=candidate_id,
            )

    def _validate_role_assignments(
        self,
        role_assignments: dict[str, list[str]],
    ) -> None:
        unknown = set(role_assignments) - set(self.definition.roles)
        if unknown:
            raise DefinitionError(f"Unknown assigned roles: {', '.join(sorted(unknown))}")
        for role in self.definition.roles.values():
            if role.kind == "dynamicItemActor":
                continue
            count = len(set(role_assignments.get(role.id, [])))
            if count < role.minimum:
                raise DefinitionError(
                    f"Role {role.id} requires at least {role.minimum} assigned user(s)."
                )
            if role.maximum != "unbounded" and count > int(role.maximum):
                raise DefinitionError(
                    f"Role {role.id} permits at most {role.maximum} assigned user(s)."
                )

    def _enter(self, instance: WorkflowInstance, node_id: str) -> None:
        steps = 0
        pending = node_id
        while pending is not None:
            steps += 1
            if steps > 1000:
                raise TaskActionError("Automatic workflow transition limit exceeded.")

            node = self.definition.nodes[pending]
            instance.current_node_id = node.id
            instance.blocked_reason = None

            if node.kind == "startEvent":
                pending = self._automatic_target(instance, node)
                continue

            if node.kind == "endEvent":
                pending = self._complete_end_event(instance, node)
                continue

            if node.kind == "exclusiveGateway":
                pending = self._gateway_target(instance, node)
                if pending is None:
                    return
                continue

            if node.kind == "serviceTask":
                self._enter_visit(instance, node.id)
                self._execute_service_task(instance, node)
                pending = self._finish_automatic_node(instance, node)
                continue

            if node.kind == "subProcess":
                self._enter_visit(instance, node.id)
                instance.emit("stageStarted", f"Started {node.name}.", node.id)
                if not self._prepare_subprocess_queue(instance, node):
                    pending = self._finish_subprocess(instance, node.id)
                    continue
                instance.subprocess_stack.append(node.id)
                pending = self.definition.starts_by_container[node.id]
                continue

            if node.kind == "userTask":
                visit = self._enter_visit(instance, node.id)
                if node.container_id == self.definition.id:
                    instance.emit("stageStarted", f"Started {node.name}.", node.id)
                self._create_node_tasks(instance, node, visit)
                if self._node_is_complete(instance, node.id, visit):
                    pending = self._finish_human_node_without_submission(instance, node, visit)
                    continue
                return

            instance.blocked_reason = {
                "type": "processTransition",
                "dependencies": [node.id],
            }
            return

    def _enter_visit(self, instance: WorkflowInstance, node_id: str) -> int:
        visit = instance.node_visits.get(node_id, 0) + 1
        instance.node_visits[node_id] = visit
        return visit

    def _automatic_target(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> str | None:
        return self._select_outgoing(instance, node)

    def _finish_automatic_node(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> str | None:
        instance.data["lastCompletedNode"] = node.id
        return self._select_outgoing(instance, node)

    def _complete_end_event(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> str | None:
        if node.container_id in self.definition.subprocess_containers:
            return self._complete_subprocess_iteration(instance, node.container_id)

        outcome = node.name.strip().lower().replace(" ", "")
        canonical = next(
            (candidate for candidate in self.definition.outcomes if candidate.lower() == outcome),
            outcome,
        )
        instance.status = "completed"
        instance.outcome = canonical
        instance.current_node_id = node.id
        instance.emit("outcome", f"Workflow ended: {canonical}.", node.id, outcome=canonical)
        return None

    def _gateway_target(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> str | None:
        target = self._select_outgoing(instance, node)
        if target is None:
            guards = [
                self.definition.flows[flow_id].guard
                for flow_id in node.outgoing
                if self.definition.flows[flow_id].guard
            ]
            instance.blocked_reason = {
                "type": "processTransition",
                "dependencies": guards,
            }
        return target

    def _select_outgoing(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> str | None:
        flows = [self.definition.flows[flow_id] for flow_id in node.outgoing]
        if len(flows) == 1 and flows[0].guard is None:
            return flows[0].target

        passing: list[Any] = []
        for flow in flows:
            if flow.guard is None:
                continue
            result = self._evaluate_guard(instance, flow.guard)
            if result:
                passing.append(flow)
        if len(passing) == 1:
            return passing[0].target
        if len(passing) > 1:
            raise TaskActionError(
                f"Gateway {node.id} has multiple passing guarded flows."
            )
        return None

    def _evaluate_guard(self, instance: WorkflowInstance, predicate: str) -> bool:
        if predicate in self.predicates:
            return bool(self.predicates[predicate](instance))

        latest_response = instance.data.get("lastHumanResponse", {})
        latest_queue = [
            instance.work_items[item_id]
            for item_id in instance.data.get("lastQueueResults", [])
            if item_id in instance.work_items
        ]

        builtins: dict[str, bool] = {
            "allConsent": self._latest_round_decisions(instance, "Task_ConsentRound")
            and all(
                decision == "consent"
                for decision in self._latest_round_decisions(instance, "Task_ConsentRound")
            ),
            "anyObjection": any(
                decision == "objection"
                for decision in self._latest_round_decisions(
                    instance,
                    "Task_ConsentRound",
                    fallback_nodes=("Task_ObjectionRound", "Task_IDMPObjectionRound"),
                )
            ),
            "decisionAmend": latest_response.get("decision") == "amend",
            "decisionWithdraw": latest_response.get("decision") == "withdraw",
            "decisionContinueOrClarify": latest_response.get("decision")
            in {"continue", "clarify"},
            "rolePresentationRequired": bool(
                instance.data.get("rolePresentationRequired", False)
            ),
            "rolePresentationNotRequired": not bool(
                instance.data.get("rolePresentationRequired", False)
            ),
            "uniqueTopCandidate": len(instance.data.get("topCandidates", [])) == 1,
            "topTie": len(instance.data.get("topCandidates", [])) > 1,
            "decisionSelectTiedCandidate": latest_response.get("decision") == "select",
            "decisionRepeatRound": latest_response.get("decision") == "repeat",
            "noValidObjection": not any(item.decision == "valid" for item in latest_queue),
            "noValidObjections": not any(item.decision == "valid" for item in latest_queue),
            "anyValidObjection": any(item.decision == "valid" for item in latest_queue),
            "openEligibility": instance.data.get("eligibilityMode") == "open",
            "closedEligibilityNoCandidates": (
                instance.data.get("eligibilityMode") == "closed"
                and not self._available_candidates(instance)
            ),
            "closedEligibilityCandidatesAvailable": (
                instance.data.get("eligibilityMode") == "closed"
                and bool(self._available_candidates(instance))
            ),
            "decisionContinue": latest_response.get("decision") == "continue",
            "decisionVoid": latest_response.get("decision") == "void",
            "allRequiredConfirmed": bool(
                instance.data.get("lastConfirmationComplete", False)
            ),
            "confirmationIncomplete": not bool(
                instance.data.get("lastConfirmationComplete", False)
            ),
        }
        return builtins.get(predicate, False)

    def _latest_round_decisions(
        self,
        instance: WorkflowInstance,
        node_id: str,
        fallback_nodes: tuple[str, ...] = (),
    ) -> list[str]:
        for candidate in (node_id, *fallback_nodes):
            visit = instance.node_visits.get(candidate)
            if not visit:
                continue
            records = [
                record
                for record in instance.node_outputs.get(candidate, [])
                if record["visit"] == visit and record["kind"] in {"round", "input"}
            ]
            if records:
                return [
                    record["response"].get("decision", record["response"].get("action"))
                    for record in records
                ]
        return []

    def _execute_service_task(self, instance: WorkflowInstance, node: Any) -> None:
        for calculation in node.extensions.get("calculation", []):
            operation = calculation["operation"]
            if operation in self.operations:
                self.operations[operation](instance)
            else:
                self._execute_builtin_operation(instance, operation)
        self._apply_artifact_actions(instance, node)

    def _execute_builtin_operation(
        self,
        instance: WorkflowInstance,
        operation: str,
    ) -> None:
        if operation == "pluralityRanking":
            nominations = instance.data.get("currentNominations", {})
            excluded = set(instance.data.get("excludedCandidates", []))
            counts = Counter(
                candidate
                for candidate in nominations.values()
                if candidate not in excluded
            )
            ranking = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
            instance.data["ranking"] = ranking
            return
        if operation == "topTie":
            ranking = instance.data.get("ranking", [])
            top_count = ranking[0][1] if ranking else 0
            instance.data["topCandidates"] = [
                candidate for candidate, count in ranking if count == top_count
            ]
            return
        if operation == "selectProposedCandidate":
            top = instance.data.get("topCandidates", [])
            latest = instance.data.get("lastHumanResponse", {})
            candidate = top[0] if len(top) == 1 else latest.get("candidateId")
            instance.data["proposedCandidate"] = candidate
            instance.emit(
                "information",
                f"Candidate proposed: {candidate}.",
                "Task_ProposeCandidate",
                candidateId=candidate,
            )
            return
        if operation == "excludeCurrentCandidate":
            candidate = instance.data.get("proposedCandidate")
            excluded = instance.data.setdefault("excludedCandidates", [])
            if candidate and candidate not in excluded:
                excluded.append(candidate)
            instance.emit(
                "information",
                f"Candidate excluded: {candidate}.",
                "Task_ExcludeCandidate",
                candidateId=candidate,
            )
            return
        if operation == "availableCandidates":
            instance.data["availableCandidates"] = self._available_candidates(instance)
            return
        if operation == "finalizeElection":
            instance.data["electedCandidate"] = instance.data.get("proposedCandidate")
            return
        if operation == "finalizeVoidElection":
            return
        raise TaskActionError(f"No operation handler registered for {operation}.")

    def _available_candidates(self, instance: WorkflowInstance) -> list[str]:
        eligible = list(instance.data.get("eligibleCandidates", []))
        excluded = set(instance.data.get("excludedCandidates", []))
        return [candidate for candidate in eligible if candidate not in excluded]

    def _create_node_tasks(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
    ) -> None:
        round_spec = node.extension("humanRound")
        if round_spec:
            self._create_round_tasks(instance, node, visit, round_spec)
            return

        confirmation = node.extension("confirmationGate")
        if confirmation:
            self._create_confirmation_tasks(instance, node, visit, confirmation)
            return

        input_spec = node.extension("input")
        if input_spec:
            users = instance.role_users(input_spec["role"])
            for user_id in users:
                self._new_task(
                    instance,
                    node.id,
                    visit,
                    user_id,
                    "input",
                    input_spec.get("responseSchema"),
                )
            return

        interaction = node.extension("controlledInteraction")
        if interaction:
            self._create_interaction_tasks(instance, node, visit, interaction)
            return

        assignment = node.extension("assignment")
        if assignment:
            for user_id in self._users_for_spec(instance, assignment):
                self._new_task(instance, node.id, visit, user_id, "input", None)

    def _create_round_tasks(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
        spec: dict[str, Any],
    ) -> None:
        users = self._users_for_spec(
            instance,
            {"role": spec["audience"], "excludeRole": spec.get("excludeRole")},
        )
        sequential = spec["ordering"] == "sequential"
        for index, user_id in enumerate(users):
            self._new_task(
                instance,
                node.id,
                visit,
                user_id,
                "round",
                spec.get("responseSchema"),
                status="open" if not sequential or index == 0 else "locked",
                metadata={"order": index},
            )

    def _create_confirmation_tasks(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
        spec: dict[str, Any],
    ) -> None:
        instance.data["lastConfirmationComplete"] = False
        for child in spec.get("_children", []):
            if child.get("_name") != "requiredConfirmation":
                continue
            for user_id in instance.role_users(child["role"]):
                self._new_task(
                    instance,
                    node.id,
                    visit,
                    user_id,
                    "confirmation",
                    spec.get("responseSchema"),
                    metadata={"claim": child["claim"], "role": child["role"]},
                )

    def _create_interaction_tasks(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
        spec: dict[str, Any],
    ) -> None:
        dynamic = node.extension("dynamicWorkCollection")
        if dynamic and dynamic.get("itemType") == "remainingObjectionApplicability":
            self._create_applicability_tasks(instance, node, visit, spec)
            return

        if spec["kind"] == "questionAnswer":
            users = self._users_for_spec(
                instance,
                {
                    "role": spec["creators"],
                    "excludeRole": spec.get("excludeCreators"),
                },
            )
            for user_id in users:
                self._new_task(
                    instance,
                    node.id,
                    visit,
                    user_id,
                    "interactionCreator",
                    spec.get("responseSchema"),
                )
            return

        closer = spec.get("closer")
        if closer:
            for user_id in instance.role_users(closer):
                self._new_task(
                    instance,
                    node.id,
                    visit,
                    user_id,
                    "closeInteraction",
                    None,
                    metadata={"action": "close"},
                )
            return

        creators = spec.get("creators", "").split()
        users: list[str] = []
        for role in creators:
            users.extend(instance.role_users(role))
        for user_id in dict.fromkeys(users):
            self._new_task(
                instance,
                node.id,
                visit,
                user_id,
                "interactionCreator",
                spec.get("responseSchema"),
            )

    def _create_applicability_tasks(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
        spec: dict[str, Any],
    ) -> None:
        if not instance.subprocess_stack:
            return
        queue = instance.active_queues[instance.subprocess_stack[-1]]
        for item_id in queue.item_ids[queue.index + 1 :]:
            item = instance.work_items[item_id]
            if item.state != "open":
                continue
            self._new_task(
                instance,
                node.id,
                visit,
                item.author_id,
                "applicability",
                spec.get("responseSchema"),
                metadata={"workItemId": item.id},
            )

    def _new_task(
        self,
        instance: WorkflowInstance,
        node_id: str,
        visit: int,
        user_id: str,
        kind: str,
        schema_ref: str | None,
        *,
        status: str = "open",
        required: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> UserTask:
        suffix = 1 + sum(
            1
            for task in instance.tasks.values()
            if task.node_id == node_id and task.visit == visit and task.user_id == user_id
        )
        task_id = f"{node_id}:{visit}:{user_id}:{suffix}"
        task = UserTask(
            id=task_id,
            node_id=node_id,
            visit=visit,
            user_id=user_id,
            kind=kind,
            status=status,
            schema_ref=schema_ref,
            required=required,
            metadata=dict(metadata or {}),
        )
        instance.tasks[task_id] = task
        return task

    def _users_for_spec(
        self,
        instance: WorkflowInstance,
        spec: dict[str, Any],
    ) -> list[str]:
        role_value = spec.get("role", "")
        roles = role_value.split()
        users: list[str] = []
        for role in roles:
            users.extend(instance.role_users(role))
        exclude_value = spec.get("excludeRole")
        excluded: set[str] = set()
        if exclude_value:
            for role in str(exclude_value).split():
                excluded.update(instance.role_users(role))
        return [user for user in dict.fromkeys(users) if user not in excluded]

    def _validate_task_semantics(
        self,
        instance: WorkflowInstance,
        task: UserTask,
        response: dict[str, Any],
    ) -> None:
        if task.kind == "interactionCreator":
            action = response.get("action")
            if action not in {"question", "done", "reaction", "pass"}:
                raise TaskActionError("Unsupported interaction creator action.")
        if task.kind == "interactionResponder" and response.get("action") not in {
            "answer",
            "decline",
        }:
            raise TaskActionError("Question response must answer or decline.")
        if task.kind == "confirmation":
            expected_claim = task.metadata.get("claim")
            if response.get("claim") != expected_claim:
                raise TaskActionError(f"Confirmation must address {expected_claim}.")

        if task.node_id in {"Task_Nominate", "Task_ChangeNominations"}:
            candidate_id = response.get("candidateId")
            if candidate_id:
                if candidate_id in set(instance.data.get("excludedCandidates", [])):
                    raise TaskActionError("An excluded candidate cannot be nominated.")
                if candidate_id not in set(instance.data.get("eligibleCandidates", [])):
                    raise TaskActionError(
                        "Candidate eligibility must be confirmed before nomination."
                    )
            if (
                task.node_id == "Task_ChangeNominations"
                and response.get("decision") == "keep"
            ):
                current = instance.data.get("currentNominations", {}).get(task.user_id)
                if current in set(instance.data.get("excludedCandidates", [])):
                    raise TaskActionError("Cannot keep an excluded nominee.")

        if (
            task.node_id == "Task_ResolveTie"
            and response.get("decision") == "select"
            and response.get("candidateId") not in instance.data.get("topCandidates", [])
        ):
            raise TaskActionError("The facilitator must select a tied candidate.")

        if task.node_id in {"Task_RecordValidity", "Task_RecordIDMPValidity"}:
            current_item = instance.current_work_item()
            if current_item and response.get("objectionId") != current_item.id:
                raise TaskActionError("Validity decision must reference the current objection.")

    def _handle_question_creator_response(
        self,
        instance: WorkflowInstance,
        task: UserTask,
        response: dict[str, Any],
    ) -> None:
        if response.get("action") != "question":
            return
        node = self.definition.nodes[task.node_id]
        spec = node.extension("controlledInteraction") or {}
        item_id = f"{task.node_id}:question:{len(instance.work_items) + 1}"
        artifact = instance.artifacts.get("proposal")
        revision = artifact.current_revision_id if artifact else None
        instance.work_items[item_id] = WorkItem(
            id=item_id,
            item_type="clarifyingQuestion",
            author_id=task.user_id,
            payload=dict(response),
            source_revision_id=revision,
            applicable_revision_id=revision,
            source_node_id=task.node_id,
            source_visit=task.visit,
        )
        for role in spec.get("responders", "").split():
            for responder in instance.role_users(role):
                self._new_task(
                    instance,
                    task.node_id,
                    task.visit,
                    responder,
                    "interactionResponder",
                    spec.get("responseSchema"),
                    metadata={"workItemId": item_id},
                )
        self._new_task(
            instance,
            task.node_id,
            task.visit,
            task.user_id,
            "interactionCreator",
            spec.get("responseSchema"),
        )

    def _handle_question_response(
        self,
        instance: WorkflowInstance,
        task: UserTask,
        response: dict[str, Any],
    ) -> None:
        item_id = task.metadata.get("workItemId")
        if item_id in instance.work_items:
            item = instance.work_items[item_id]
            item.state = "resolved"
            item.decision = response.get("action")

    def _handle_applicability_response(
        self,
        instance: WorkflowInstance,
        task: UserTask,
        response: dict[str, Any],
    ) -> None:
        item_id = task.metadata.get("workItemId")
        if item_id not in instance.work_items:
            return
        item = instance.work_items[item_id]
        decision = response.get("decision")
        if decision == "withdrawn":
            item.state = "withdrawn"
        else:
            artifact = instance.artifacts.get("proposal")
            item.applicable_revision_id = (
                artifact.current_revision_id if artifact else item.applicable_revision_id
            )

    def _unlock_next_sequential_task(
        self,
        instance: WorkflowInstance,
        node_id: str,
        visit: int,
    ) -> None:
        tasks = sorted(
            (
                task
                for task in instance.tasks.values()
                if task.node_id == node_id
                and task.visit == visit
                and task.kind == "round"
            ),
            key=lambda task: task.metadata.get("order", 0),
        )
        if any(task.status == "open" for task in tasks):
            return
        next_locked = next((task for task in tasks if task.status == "locked"), None)
        if next_locked:
            next_locked.status = "open"

    def _node_is_complete(
        self,
        instance: WorkflowInstance,
        node_id: str,
        visit: int,
    ) -> bool:
        tasks = [
            task
            for task in instance.tasks.values()
            if task.node_id == node_id and task.visit == visit and task.required
        ]
        if not tasks:
            return True

        node = self.definition.nodes[node_id]
        interaction = node.extension("controlledInteraction")
        if interaction and interaction.get("kind") == "questionAnswer":
            creators = [task for task in tasks if task.kind == "interactionCreator"]
            responders = [task for task in tasks if task.kind == "interactionResponder"]
            closer = [task for task in tasks if task.kind == "closeInteraction"]
            creators_done = bool(creators) and all(
                task.status == "completed"
                and task.response
                and task.response.get("action") == "done"
                for task in creators
                if not self._has_newer_creator_task(instance, task)
            )
            active_creator_tasks = [
                task
                for task in creators
                if not self._has_newer_creator_task(instance, task)
            ]
            creators_done = bool(active_creator_tasks) and all(
                task.status == "completed"
                and task.response
                and task.response.get("action") == "done"
                for task in active_creator_tasks
            )
            responders_done = all(task.status == "completed" for task in responders)
            if creators_done and responders_done and not closer:
                for user_id in instance.role_users(interaction["closer"]):
                    self._new_task(
                        instance,
                        node_id,
                        visit,
                        user_id,
                        "closeInteraction",
                        None,
                        metadata={"action": "close"},
                    )
                return False
            if closer:
                return all(task.status == "completed" for task in closer)
            return False

        return all(task.status == "completed" for task in tasks)

    def _has_newer_creator_task(
        self,
        instance: WorkflowInstance,
        task: UserTask,
    ) -> bool:
        return any(
            other.node_id == task.node_id
            and other.visit == task.visit
            and other.user_id == task.user_id
            and other.kind == "interactionCreator"
            and other.id != task.id
            and int(other.id.rsplit(":", 1)[-1]) > int(task.id.rsplit(":", 1)[-1])
            for other in instance.tasks.values()
        )

    def _complete_human_node(
        self,
        instance: WorkflowInstance,
        node_id: str,
        visit: int,
    ) -> None:
        node = self.definition.nodes[node_id]
        self._update_node_semantics(instance, node, visit)
        self._apply_artifact_actions(instance, node)
        self._mark_stage_completed(instance, node)
        target = self._select_outgoing(instance, node)
        self._enter(instance, target) if target else None

    def _finish_human_node_without_submission(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
    ) -> str | None:
        self._update_node_semantics(instance, node, visit)
        self._apply_artifact_actions(instance, node)
        self._mark_stage_completed(instance, node)
        return self._select_outgoing(instance, node)

    def _mark_stage_completed(self, instance: WorkflowInstance, node: Any) -> None:
        instance.data["lastCompletedNode"] = node.id
        if node.container_id == self.definition.id:
            instance.last_completed_stage_id = node.id
            instance.emit("stageCompleted", f"Completed {node.name}.", node.id)
        else:
            instance.recent_activity = f"Completed {node.name}"

    def _update_node_semantics(
        self,
        instance: WorkflowInstance,
        node: Any,
        visit: int,
    ) -> None:
        records = [
            record
            for record in instance.node_outputs.get(node.id, [])
            if record["visit"] == visit
        ]

        if node.id == "Task_Nominate":
            instance.data["currentNominations"] = {
                record["userId"]: record["response"]["candidateId"]
                for record in records
                if record["kind"] == "round"
            }

        if node.id == "Task_ChangeNominations":
            nominations = instance.data.setdefault("currentNominations", {})
            excluded = set(instance.data.get("excludedCandidates", []))
            for record in records:
                if record["kind"] != "round":
                    continue
                response = record["response"]
                user_id = record["userId"]
                if response["decision"] == "keep":
                    if nominations.get(user_id) in excluded:
                        raise TaskActionError("Cannot keep an excluded nominee.")
                else:
                    nominations[user_id] = response["candidateId"]

        if node.id in {"Task_RecordValidity", "Task_RecordIDMPValidity"}:
            item = instance.current_work_item()
            response = next(
                (
                    record["response"]
                    for record in reversed(records)
                    if record["kind"] == "input"
                ),
                {},
            )
            if item:
                item.decision = response.get("decision")
                item.state = (
                    "open" if response.get("decision") == "valid" else "resolved"
                )

        if node.id == "Task_ConfirmIntegration":
            confirmations = [
                record["response"].get("decision")
                for record in records
                if record["kind"] == "confirmation"
            ]
            instance.data["lastConfirmationComplete"] = bool(confirmations) and all(
                decision == "confirmed" for decision in confirmations
            )

    def _apply_artifact_actions(self, instance: WorkflowInstance, node: Any) -> None:
        for action in node.extensions.get("artifactAction", []):
            artifact = instance.artifacts[action["artifactRef"]]
            action_name = action["action"]
            if action_name in {"createInitialRevision", "createRevision"}:
                response = dict(instance.data.get("lastHumanResponse", {}))
                actor = str(instance.data.get("lastHumanActor", "system"))
                sequence = len(artifact.revisions) + 1
                revision_id = f"{artifact.id}-r{sequence}"
                revision = ArtifactRevision(
                    id=revision_id,
                    supersedes=artifact.current_revision_id,
                    content=response,
                    created_by=actor,
                    sequence=sequence,
                )
                artifact.revisions.append(revision)
                artifact.current_revision_id = revision_id
                artifact.lifecycle_state = "proposed"
                instance.emit(
                    "artifact",
                    f"Created {artifact.id} revision {revision_id}.",
                    node.id,
                    artifactId=artifact.id,
                    revisionId=revision_id,
                )
            elif action_name == "adopt":
                artifact.lifecycle_state = "adopted"
                instance.emit(
                    "artifact",
                    f"Adopted {artifact.id} revision {artifact.current_revision_id}.",
                    node.id,
                    artifactId=artifact.id,
                    revisionId=artifact.current_revision_id,
                )
            elif action_name == "withdraw":
                artifact.lifecycle_state = "withdrawn"
                instance.emit(
                    "artifact",
                    f"Withdrew {artifact.id}.",
                    node.id,
                    artifactId=artifact.id,
                    revisionId=artifact.current_revision_id,
                )

    def _prepare_subprocess_queue(
        self,
        instance: WorkflowInstance,
        node: Any,
    ) -> bool:
        queue_spec = node.extension("managedQueue")
        collection = node.extension("dynamicWorkCollection")
        if not queue_spec or not collection:
            return True

        item_type = queue_spec["itemType"]
        item_ids: list[str]
        if item_type in {"objection", "potentialObjection"}:
            item_ids = self._create_items_from_latest_objection_round(
                instance,
                item_type,
            )
        elif item_type == "validObjection":
            item_ids = [
                item_id
                for item_id in instance.data.get("lastQueueResults", [])
                if item_id in instance.work_items
                and instance.work_items[item_id].decision == "valid"
            ]
        else:
            item_ids = [
                item.id
                for item in instance.work_items.values()
                if item.item_type == item_type and item.state == "open"
            ]

        instance.active_queues[node.id] = QueueState(
            subprocess_id=node.id,
            item_ids=item_ids,
        )
        if not item_ids:
            instance.data["lastQueueResults"] = []
        return bool(item_ids)

    def _create_items_from_latest_objection_round(
        self,
        instance: WorkflowInstance,
        item_type: str,
    ) -> list[str]:
        source_node = next(
            (
                candidate
                for candidate in ("Task_ObjectionRound", "Task_IDMPObjectionRound")
                if instance.node_visits.get(candidate)
                and instance.data.get("lastCompletedNode") == candidate
            ),
            None,
        )
        if source_node is None:
            source_node = str(instance.data.get("lastCompletedNode", ""))
        visit = instance.node_visits.get(source_node, 0)
        artifact = instance.artifacts.get("proposal")
        revision = artifact.current_revision_id if artifact else None
        item_ids: list[str] = []
        for record in instance.node_outputs.get(source_node, []):
            response = record["response"]
            if record["visit"] != visit or response.get("decision") != "objection":
                continue
            item_id = f"{item_type}:{source_node}:{visit}:{record['userId']}"
            instance.work_items[item_id] = WorkItem(
                id=item_id,
                item_type=item_type,
                author_id=record["userId"],
                payload=dict(response),
                source_revision_id=revision,
                applicable_revision_id=revision,
                source_node_id=source_node,
                source_visit=visit,
            )
            item_ids.append(item_id)
        return item_ids

    def _complete_subprocess_iteration(
        self,
        instance: WorkflowInstance,
        subprocess_id: str,
    ) -> str | None:
        queue = instance.active_queues.get(subprocess_id)
        if queue:
            item = instance.current_work_item()
            if item and subprocess_id == "Sub_IntegrationQueue":
                if instance.data.get("lastConfirmationComplete"):
                    item.state = "resolved"
            queue.index += 1
            while queue.index < len(queue.item_ids):
                candidate = instance.work_items[queue.item_ids[queue.index]]
                if candidate.state == "open":
                    break
                queue.index += 1
            if queue.index < len(queue.item_ids):
                return self.definition.starts_by_container[subprocess_id]
            instance.data["lastQueueResults"] = list(queue.item_ids)

        if instance.subprocess_stack and instance.subprocess_stack[-1] == subprocess_id:
            instance.subprocess_stack.pop()
        return self._finish_subprocess(instance, subprocess_id)

    def _finish_subprocess(
        self,
        instance: WorkflowInstance,
        subprocess_id: str,
    ) -> str | None:
        node = self.definition.nodes[subprocess_id]
        instance.last_completed_stage_id = subprocess_id
        instance.data["lastCompletedNode"] = subprocess_id
        instance.emit("stageCompleted", f"Completed {node.name}.", node.id)
        return self._select_outgoing(instance, node)

    def _current_major_stage_id(self, instance: WorkflowInstance) -> str | None:
        if instance.status == "completed":
            return None
        if instance.subprocess_stack:
            return instance.subprocess_stack[0]
        return instance.current_node_id

    def _waiting_reason(
        self,
        instance: WorkflowInstance,
        user_id: str,
    ) -> dict[str, Any] | None:
        if instance.blocked_reason:
            return dict(instance.blocked_reason)
        node_id = instance.current_node_id
        if not node_id:
            return None
        visit = instance.node_visits.get(node_id, 0)
        tasks = [
            task
            for task in instance.tasks.values()
            if task.node_id == node_id
            and task.visit == visit
            and task.status in {"open", "locked"}
        ]
        open_assignees = [task.user_id for task in tasks if task.status == "open"]
        user_locked = any(
            task.user_id == user_id and task.status == "locked" for task in tasks
        )
        if user_locked:
            return {
                "type": "priorTurn",
                "dependencies": open_assignees,
            }
        if open_assignees:
            return {
                "type": "actorTask",
                "dependencies": list(dict.fromkeys(open_assignees)),
            }
        return {"type": "processTransition", "dependencies": [node_id]}
