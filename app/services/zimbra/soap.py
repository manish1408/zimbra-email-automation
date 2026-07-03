from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
ZIMBRA_NS = "urn:zimbra"
ZIMBRA_ADMIN_NS = "urn:zimbraAdmin"
ZIMBRA_MAIL_NS = "urn:zimbraMail"


def local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def normalize_zimbra_date(raw: str | None) -> str | None:
    """Convert Zimbra epoch-ms (or seconds) strings to ISO-8601 UTC."""
    if not raw:
        return None
    value = raw.strip()
    if not value.isdigit():
        return value
    ms = int(value)
    if len(value) <= 10:
        ms *= 1000
    from datetime import UTC, datetime

    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat()


def build_envelope(
    body_xml: str,
    auth_token: str | None = None,
    target_account: str | None = None,
) -> str:
    header_parts = [
        f'<context xmlns="{ZIMBRA_NS}">',
        '<userAgent name="zimbra-email-automation" version="1.0"/>',
    ]
    if auth_token:
        header_parts.append(f"<authToken>{auth_token}</authToken>")
    if target_account:
        header_parts.append(
            f'<target type="account">{target_account}</target>'
        )
    header_parts.append("</context>")

    return (
        f'<soap:Envelope xmlns:soap="{SOAP_NS}">'
        f"<soap:Header>{''.join(header_parts)}</soap:Header>"
        f"<soap:Body>{body_xml}</soap:Body>"
        "</soap:Envelope>"
    )


def parse_response(xml_text: str) -> ET.Element:
    root = ET.fromstring(xml_text)
    body = root.find(f"{{{SOAP_NS}}}Body")
    if body is None:
        raise ValueError("SOAP response missing Body element")

    fault = body.find(f"{{{SOAP_NS}}}Fault")
    if fault is not None:
        reason = fault.findtext(".//faultstring") or fault.findtext(".//Reason/Text")
        code = fault.findtext(".//errorCode") or fault.findtext(".//Code/Value")
        detail = fault.findtext(".//Detail/*") or ""
        message = reason or "Unknown Zimbra SOAP fault"
        if code:
            message = f"{message} (code={code})"
        if detail:
            message = f"{message}: {detail}"
        raise ZimbraSoapError(message, raw_xml=xml_text)

    for child in body:
        return child

    raise ValueError("SOAP response body is empty")


class ZimbraSoapError(Exception):
    def __init__(self, message: str, raw_xml: str | None = None):
        super().__init__(message)
        self.raw_xml = raw_xml


def element_to_dict(element: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if element.attrib:
        result["@attrs"] = dict(element.attrib)

    text = (element.text or "").strip()
    children = list(element)

    if not children:
        if text:
            return text
        return result or {}

    child_map: dict[str, list[Any]] = {}
    for child in children:
        child_value = element_to_dict(child)
        child_map.setdefault(local_name(child.tag), []).append(child_value)

    for key, values in child_map.items():
        result[key] = values[0] if len(values) == 1 else values

    if text:
        result["#text"] = text

    return result


def find_by_local_name(
    element: ET.Element,
    name: str,
    *,
    recursive: bool = True,
) -> ET.Element | None:
    if not recursive:
        for child in element:
            if local_name(child.tag) == name:
                return child
        return None

    for node in element.iter():
        if local_name(node.tag) == name:
            return node
    return None


def find_all_by_local_name(
    element: ET.Element,
    name: str,
    *,
    recursive: bool = True,
) -> list[ET.Element]:
    if not recursive:
        return [child for child in element if local_name(child.tag) == name]
    return [node for node in element.iter() if local_name(node.tag) == name]


def find_text(element: ET.Element, path: str, default: str | None = None) -> str | None:
    """Find element text by local tag name (namespace-agnostic)."""
    if path.startswith(".//"):
        name = path[3:]
        node = find_by_local_name(element, name, recursive=True)
    elif path.startswith("./"):
        name = path[2:]
        node = find_by_local_name(element, name, recursive=False)
    else:
        node = find_by_local_name(element, path, recursive=True)

    if node is None or node.text is None:
        return default
    return node.text.strip()


def find_all(element: ET.Element, path: str) -> list[ET.Element]:
    """Find elements by local tag name (namespace-agnostic)."""
    if path.startswith(".//"):
        name = path[3:]
        return find_all_by_local_name(element, name, recursive=True)
    if path.startswith("./"):
        name = path[2:]
        return find_all_by_local_name(element, name, recursive=False)
    return find_all_by_local_name(element, path, recursive=True)
