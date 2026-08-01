from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from .model import (
    DefinitionError,
    FlowDefinition,
    NodeDefinition,
    RoleDefinition,
    WorkflowDefinition,
)


BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CWP_NS = "urn:s-protocol:consent-workflow:0.2"

FLOW_NODE_NAMES = {
    "businessRuleTask",
    "callActivity",
    "endEvent",
    "exclusiveGateway",
    "inclusiveGateway",
    "intermediateCatchEvent",
    "intermediateThrowEvent",
    "manualTask",
    "parallelGateway",
    "receiveTask",
    "scriptTask",
    "sendTask",
    "serviceTask",
    "startEvent",
    "subProcess",
    "task",
    "userTask",
}


def qname(namespace: str, local_name: str) -> str:
    return f"{{{namespace}}}{local_name}"


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_extension(element: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = dict(element.attrib)
    children: list[dict[str, Any]] = []
    for child in element:
        parsed = parse_extension(child)
        parsed["_name"] = local_name(child.tag)
        children.append(parsed)
    if children:
        result["_children"] = children
    return result


def direct_cwp_extensions(element: ET.Element) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    extension_elements = element.find(qname(BPMN_NS, "extensionElements"))
    if extension_elements is None:
        return result
    for child in extension_elements:
        if not child.tag.startswith(f"{{{CWP_NS}}}"):
            continue
        result.setdefault(local_name(child.tag), []).append(parse_extension(child))
    return result


def response_schema_references(extensions: dict[str, list[dict[str, Any]]]) -> set[str]:
    references: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            reference = value.get("responseSchema")
            if isinstance(reference, str):
                references.add(reference)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(extensions)
    return references


def load_workflow(path: str | Path) -> WorkflowDefinition:
    source_path = Path(path).resolve()
    try:
        tree = ET.parse(source_path)
    except (OSError, ET.ParseError) as exc:
        raise DefinitionError(f"Cannot parse {source_path}: {exc}") from exc

    root = tree.getroot()
    if root.tag != qname(BPMN_NS, "definitions"):
        raise DefinitionError("Root element must be BPMN definitions.")

    processes = root.findall(qname(BPMN_NS, "process"))
    if len(processes) != 1:
        raise DefinitionError("A workflow file must contain exactly one BPMN process.")
    process = processes[0]
    process_id = process.get("id")
    if not process_id:
        raise DefinitionError("BPMN process requires an id.")

    process_extensions = direct_cwp_extensions(process)
    profiles = process_extensions.get("profile", [])
    if len(profiles) != 1:
        raise DefinitionError("BPMN process requires exactly one cwp:profile.")
    profile = profiles[0]

    roles: dict[str, RoleDefinition] = {}
    artifacts: dict[str, dict[str, Any]] = {}
    outcomes: set[str] = set()
    for child in profile.get("_children", []):
        child_name = child.get("_name")
        if child_name == "role":
            role_id = child["id"]
            roles[role_id] = RoleDefinition(
                id=role_id,
                kind=child["kind"],
                minimum=int(child["min"]),
                maximum=child["max"],
            )
        elif child_name == "artifactDefinition":
            artifacts[child["id"]] = {
                key: value for key, value in child.items() if not key.startswith("_")
            }
        elif child_name == "outcome":
            outcomes.add(child["code"])

    nodes: dict[str, NodeDefinition] = {}
    flows: dict[str, FlowDefinition] = {}
    starts_by_container: dict[str, str] = {}
    subprocess_containers: set[str] = set()
    schema_references: set[str] = set()
    schema_references.update(response_schema_references(process_extensions))

    def parse_container(container: ET.Element, container_id: str) -> None:
        starts: list[str] = []
        for child in container:
            if not child.tag.startswith(f"{{{BPMN_NS}}}"):
                continue
            kind = local_name(child.tag)
            if kind not in FLOW_NODE_NAMES:
                continue
            node_id = child.get("id")
            if not node_id:
                raise DefinitionError(f"{kind} in {container_id} has no id.")
            if node_id in nodes:
                raise DefinitionError(f"Duplicate BPMN node id {node_id}.")
            extensions = direct_cwp_extensions(child)
            schema_references.update(response_schema_references(extensions))
            nodes[node_id] = NodeDefinition(
                id=node_id,
                name=child.get("name", node_id),
                kind=kind,
                container_id=container_id,
                extensions=extensions,
            )
            if kind == "startEvent":
                starts.append(node_id)
            if kind == "subProcess":
                subprocess_containers.add(node_id)
                parse_container(child, node_id)

        if len(starts) != 1:
            raise DefinitionError(
                f"Container {container_id} requires exactly one start event; found {len(starts)}."
            )
        starts_by_container[container_id] = starts[0]

        for child in container.findall(qname(BPMN_NS, "sequenceFlow")):
            flow_id = child.get("id")
            source = child.get("sourceRef")
            target = child.get("targetRef")
            if not flow_id or not source or not target:
                raise DefinitionError(f"Incomplete sequenceFlow in {container_id}.")
            if flow_id in flows:
                raise DefinitionError(f"Duplicate sequenceFlow id {flow_id}.")
            extensions = direct_cwp_extensions(child)
            guards = extensions.get("guard", [])
            guard = guards[0].get("predicate") if guards else None
            flows[flow_id] = FlowDefinition(
                id=flow_id,
                source=source,
                target=target,
                guard=guard,
            )

    parse_container(process, process_id)

    for flow in flows.values():
        if flow.source not in nodes or flow.target not in nodes:
            raise DefinitionError(f"Flow {flow.id} contains an unresolved node reference.")
        nodes[flow.source].outgoing.append(flow.id)

    schemas: dict[Path, dict[str, Any]] = {}
    for reference in schema_references:
        relative_path = reference.split("#", 1)[0]
        schema_path = (source_path.parent / relative_path).resolve()
        if schema_path in schemas:
            continue
        try:
            schemas[schema_path] = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise DefinitionError(f"Cannot load response schema {schema_path}: {exc}") from exc

    return WorkflowDefinition(
        id=process_id,
        name=process.get("name", process_id),
        source_path=source_path,
        template_id=profile["templateId"],
        template_version=profile["templateVersion"],
        roles=roles,
        outcomes=outcomes,
        artifacts=artifacts,
        nodes=nodes,
        flows=flows,
        starts_by_container=starts_by_container,
        subprocess_containers=subprocess_containers,
        process_extensions=process_extensions,
        schemas=schemas,
    )
