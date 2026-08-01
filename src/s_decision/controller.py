"""HTTP routes for S-decision."""

from __future__ import annotations

from starlette.requests import Request
from starlette.routing import Route


def build_routes(logic, runtime) -> list[Route]:
    async def api_process(request: Request):
        requested = request.query_params.get("process_uuid")
        return runtime.composite_response(
            lambda: logic.process_snapshot(requested),
            lambda snapshot: runtime.collaboration.network_info(
                snapshot.get("topic_uuid"),
            ),
            logic.merge_process_observation,
        )

    async def api_create(request: Request):
        data = await request.json()
        return await _mutation(runtime, data, lambda: logic.create_process(
            data.get("title", ""),
            data.get("definition_id", "integrative-election"),
            data.get("definition_version", "0.2.0"),
        ))

    async def api_select(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.select_process(data["process_uuid"]),
        )

    async def api_rename(request: Request):
        data = await request.json()
        return await _mutation(runtime, data, lambda: logic.rename_process(
            data["process_uuid"],
            data.get("title", ""),
            data.get("expected_content_hash"),
        ))

    async def api_delete(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.delete_process(data["process_uuid"]),
        )

    async def api_assign(request: Request):
        data = await request.json()
        return await _mutation(runtime, data, lambda: logic.set_assignment(
            data["process_uuid"],
            data["identity_uuid"],
            data["role"],
            data.get("required"),
        ))

    async def api_start(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.start_process(data["process_uuid"]),
        )

    async def api_configure_election(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.configure_election(
                data["process_uuid"],
                data.get("eligible_candidates") or [],
                bool(data.get("role_presentation_required")),
            ),
        )

    async def api_submit(request: Request):
        data = await request.json()
        return await _mutation(runtime, data, lambda: logic.submit_task(
            data["process_uuid"],
            data["task_id"],
            data.get("response") or {},
            data.get("expected_runtime_content_hash"),
        ))

    async def api_acknowledge(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.acknowledge_information(data["process_uuid"]),
        )

    async def api_agenda_create(request: Request):
        data = await request.json()
        return await _mutation(runtime, data, lambda: logic.create_agenda_item(
            data["process_uuid"], data.get("text", ""), data.get("priority"),
        ))

    async def api_agenda_delete(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.delete_agenda_item(data["item_uuid"]),
        )

    async def api_agenda_priority(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.set_agenda_item_priority(
                data["item_uuid"], data.get("priority"),
            ),
        )

    async def api_agenda_move(request: Request):
        data = await request.json()
        return await _mutation(
            runtime, data,
            lambda: logic.move_agenda_item(
                data["item_uuid"], int(data.get("index", 0)),
            ),
        )

    return [
        Route("/api/decision/process", api_process),
        Route("/api/decision/processes/create", api_create, methods=["POST"]),
        Route("/api/decision/processes/select", api_select, methods=["POST"]),
        Route("/api/decision/processes/rename", api_rename, methods=["POST"]),
        Route("/api/decision/processes/delete", api_delete, methods=["POST"]),
        Route("/api/decision/assignments/set", api_assign, methods=["POST"]),
        Route("/api/decision/processes/start", api_start, methods=["POST"]),
        Route(
            "/api/decision/processes/configure_election",
            api_configure_election,
            methods=["POST"],
        ),
        Route("/api/decision/tasks/submit", api_submit, methods=["POST"]),
        Route(
            "/api/decision/information/acknowledge",
            api_acknowledge,
            methods=["POST"],
        ),
        Route("/api/decision/agenda/create", api_agenda_create, methods=["POST"]),
        Route("/api/decision/agenda/delete", api_agenda_delete, methods=["POST"]),
        Route(
            "/api/decision/agenda/set_priority",
            api_agenda_priority,
            methods=["POST"],
        ),
        Route("/api/decision/agenda/move", api_agenda_move, methods=["POST"]),
    ]


async def _mutation(runtime, data: dict, operation):
    return await runtime.mutation_response(
        operation,
        mutation_id=data.get("mutation_id"),
        invalidates=("process",),
    )
