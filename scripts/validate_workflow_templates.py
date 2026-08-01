from __future__ import annotations

import copy
import json
import sys
from collections import deque
from pathlib import Path

try:
    from lxml import etree
except ImportError as exc:
    raise SystemExit("Validation requires lxml.") from exc


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = PROJECT_ROOT / "src" / "s_flow" / "workflow" / "templates"
XSD_PATH = PROJECT_ROOT / "schema" / "consent-workflow-profile.xsd"

BPMN_NS = "http://www.omg.org/spec/BPMN/20100524/MODEL"
CWP_NS = "urn:s-protocol:consent-workflow:0.2"
NS = {"bpmn": BPMN_NS, "cwp": CWP_NS}

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

ROLE_ATTRIBUTES = {
    "actorRole",
    "audience",
    "closer",
    "controllerRole",
    "excludeCreators",
    "excludeRole",
    "role",
}

ROLE_LIST_ATTRIBUTES = {"creators", "responders"}


def local_name(element: etree._Element) -> str:
    return etree.QName(element).localname


def direct_children(container: etree._Element, names: set[str]) -> list[etree._Element]:
    return [
        child
        for child in container
        if etree.QName(child).namespace == BPMN_NS and local_name(child) in names
    ]


def validate_json_reference(
    template_path: Path,
    reference: str,
    cache: dict[Path, dict],
    errors: list[str],
) -> None:
    if "#" not in reference:
        errors.append(f"{template_path.name}: responseSchema lacks JSON Pointer: {reference}")
        return

    relative_path, fragment = reference.split("#", 1)
    schema_path = (template_path.parent / relative_path).resolve()
    if not schema_path.is_file():
        errors.append(f"{template_path.name}: missing response schema {schema_path}")
        return

    if schema_path not in cache:
        try:
            document = json.loads(schema_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{schema_path.name}: invalid JSON: {exc}")
            return
        if document.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{schema_path.name}: expected JSON Schema draft 2020-12")
        if not isinstance(document.get("$defs"), dict):
            errors.append(f"{schema_path.name}: missing $defs object")
        cache[schema_path] = document

    document = cache[schema_path]
    parts = [part.replace("~1", "/").replace("~0", "~") for part in fragment.split("/") if part]
    current: object = document
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            errors.append(f"{template_path.name}: unresolved schema fragment #{fragment}")
            return
        current = current[part]


def validate_container_graph(
    template_name: str,
    container: etree._Element,
    errors: list[str],
) -> None:
    nodes = direct_children(container, FLOW_NODE_NAMES)
    node_ids = {node.get("id") for node in nodes if node.get("id")}
    flows = direct_children(container, {"sequenceFlow"})

    starts = [node.get("id") for node in nodes if local_name(node) == "startEvent"]
    ends = [node.get("id") for node in nodes if local_name(node) == "endEvent"]
    label = container.get("id", local_name(container))

    if not starts:
        errors.append(f"{template_name}: {label} has no start event")
        return
    if not ends:
        errors.append(f"{template_name}: {label} has no end event")

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
    for flow in flows:
        source = flow.get("sourceRef")
        target = flow.get("targetRef")
        if source not in node_ids:
            errors.append(f"{template_name}: {flow.get('id')} has unknown sourceRef {source} in {label}")
            continue
        if target not in node_ids:
            errors.append(f"{template_name}: {flow.get('id')} has unknown targetRef {target} in {label}")
            continue
        adjacency[source].add(target)

    reached: set[str] = set()
    queue = deque(starts)
    while queue:
        node_id = queue.popleft()
        if node_id in reached:
            continue
        reached.add(node_id)
        queue.extend(adjacency.get(node_id, ()))

    unreachable = sorted(node_ids - reached)
    if unreachable:
        errors.append(f"{template_name}: unreachable nodes in {label}: {', '.join(unreachable)}")

    if ends and not any(end in reached for end in ends):
        errors.append(f"{template_name}: no reachable end event in {label}")


def validate_template(
    template_path: Path,
    cwp_schema: etree.XMLSchema,
    json_cache: dict[Path, dict],
) -> list[str]:
    errors: list[str] = []
    parser = etree.XMLParser(remove_blank_text=False)

    try:
        tree = etree.parse(str(template_path), parser)
    except etree.XMLSyntaxError as exc:
        return [f"{template_path.name}: malformed XML: {exc}"]

    root = tree.getroot()
    if root.tag != f"{{{BPMN_NS}}}definitions":
        errors.append(f"{template_path.name}: root is not BPMN definitions")

    ids: dict[str, etree._Element] = {}
    for element in tree.iter():
        element_id = element.get("id")
        if not element_id:
            continue
        if element_id in ids:
            errors.append(f"{template_path.name}: duplicate id {element_id}")
        ids[element_id] = element

    processes = tree.xpath("//bpmn:process", namespaces=NS)
    if len(processes) != 1:
        errors.append(f"{template_path.name}: expected exactly one process")
    for process in processes:
        profiles = process.xpath("./bpmn:extensionElements/cwp:profile", namespaces=NS)
        if len(profiles) != 1:
            errors.append(f"{template_path.name}: process must contain exactly one cwp:profile")
            continue

        roles = {role.get("id") for role in profiles[0].xpath("./cwp:role", namespaces=NS)}

        for extension in tree.xpath("//bpmn:extensionElements/cwp:*", namespaces=NS):
            candidate = copy.deepcopy(extension)
            if not cwp_schema.validate(etree.ElementTree(candidate)):
                message = "; ".join(error.message for error in cwp_schema.error_log)
                errors.append(
                    f"{template_path.name}: invalid cwp:{local_name(extension)} on "
                    f"{extension.getparent().getparent().get('id', 'unknown')}: {message}"
                )

            response_schema = extension.get("responseSchema")
            if response_schema:
                validate_json_reference(template_path, response_schema, json_cache, errors)

        for cwp_element in process.xpath(".//cwp:*", namespaces=NS):
            if local_name(cwp_element) == "role":
                continue
            for attribute in ROLE_ATTRIBUTES:
                value = cwp_element.get(attribute)
                if value and value not in roles:
                    errors.append(
                        f"{template_path.name}: cwp:{local_name(cwp_element)} references "
                        f"unknown role {value}"
                    )
            for attribute in ROLE_LIST_ATTRIBUTES:
                value = cwp_element.get(attribute)
                if not value:
                    continue
                for role in value.split():
                    if role not in roles:
                        errors.append(
                            f"{template_path.name}: cwp:{local_name(cwp_element)} references "
                            f"unknown role {role}"
                        )

        validate_container_graph(template_path.name, process, errors)
        for subprocess in process.xpath(".//bpmn:subProcess", namespaces=NS):
            validate_container_graph(template_path.name, subprocess, errors)

    for flow in tree.xpath("//bpmn:sequenceFlow", namespaces=NS):
        for attribute in ("sourceRef", "targetRef"):
            reference = flow.get(attribute)
            if reference not in ids:
                errors.append(
                    f"{template_path.name}: {flow.get('id')} has unresolved {attribute}={reference}"
                )

    return errors


def main() -> int:
    try:
        cwp_schema = etree.XMLSchema(etree.parse(str(XSD_PATH)))
    except (OSError, etree.XMLSyntaxError, etree.XMLSchemaParseError) as exc:
        print(f"Invalid CWP XSD: {exc}", file=sys.stderr)
        return 1

    templates = sorted(TEMPLATE_DIR.glob("*.bpmn"))
    if not templates:
        print("No BPMN templates found.", file=sys.stderr)
        return 1

    json_cache: dict[Path, dict] = {}
    errors: list[str] = []
    for template in templates:
        errors.extend(validate_template(template, cwp_schema, json_cache))

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(
        f"Validated {len(templates)} BPMN templates, "
        f"{len(json_cache)} response schemas, and all CWP extensions."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
