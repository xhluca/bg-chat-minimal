"""Page observation extraction: AX tree, DOM snapshot, screenshots."""

import base64
import io
import logging
import pkgutil
import re

import playwright.sync_api

from .constants import BROWSERGYM_ID_ATTRIBUTE as BID_ATTR

MARK_FRAMES_MAX_TRIES = 3
logger = logging.getLogger(__name__)


class MarkingError(Exception):
    pass


def _pre_extract(page: playwright.sync_api.Page, tags_to_mark="standard_html", lenient=False):
    js = pkgutil.get_data(__name__, "javascript/frame_mark_elements.js").decode("utf-8")

    def mark_frames_recursive(frame, frame_bid: str):
        warnings = frame.evaluate(js, [frame_bid, BID_ATTR, tags_to_mark])
        for msg in warnings:
            logger.warning(msg)

        for child_frame in frame.child_frames:
            if child_frame.is_detached():
                continue
            child_frame_elem = child_frame.frame_element()
            if not child_frame_elem.content_frame() == child_frame:
                continue
            sandbox_attr = child_frame_elem.get_attribute("sandbox")
            if sandbox_attr is not None and "allow-scripts" not in sandbox_attr.split():
                continue
            child_frame_bid = child_frame_elem.get_attribute(BID_ATTR)
            if child_frame_bid is None:
                if lenient:
                    continue
                raise MarkingError("Cannot mark a child frame without a bid.")
            mark_frames_recursive(child_frame, frame_bid=child_frame_bid)

    mark_frames_recursive(page.main_frame, frame_bid="")


def _post_extract(page: playwright.sync_api.Page):
    js = pkgutil.get_data(__name__, "javascript/frame_unmark_elements.js").decode("utf-8")

    for frame in page.frames:
        try:
            if not frame == page.main_frame:
                if not frame.frame_element().content_frame() == frame:
                    continue
                sandbox_attr = frame.frame_element().get_attribute("sandbox")
                if sandbox_attr is not None and "allow-scripts" not in sandbox_attr.split():
                    continue
                bid = frame.frame_element().get_attribute(BID_ATTR)
                if bid is None:
                    continue
            frame.evaluate(js)
        except playwright.sync_api.Error as e:
            if "Frame was detached" in str(e) or "Frame has been detached" in str(e):
                pass
            else:
                raise


def extract_screenshot_base64(page: playwright.sync_api.Page, exclude_right_px: int = 0) -> str:
    """Capture a PNG screenshot and return it as a base64 string. If
    ``exclude_right_px`` is set, crop that many pixels from the right side
    (used to omit the bg-chat overlay panel from screenshots fed to the model)."""
    if exclude_right_px > 0:
        viewport = page.viewport_size or {"width": 1280, "height": 720}
        width = max(1, viewport["width"] - exclude_right_px)
        img_bytes = page.screenshot(
            clip={"x": 0, "y": 0, "width": width, "height": viewport["height"]},
            type="png",
        )
        return base64.b64encode(img_bytes).decode()
    cdp = page.context.new_cdp_session(page)
    result = cdp.send("Page.captureScreenshot", {"format": "png"})
    cdp.detach()
    return result["data"]


__BID_EXPR = r"([a-zA-Z0-9]+)"
__DATA_REGEXP = re.compile(r"^browsergym_id_" + __BID_EXPR + r"\s?" + r"(.*)")


def _extract_data_items_from_aria(string: str):
    match = __DATA_REGEXP.fullmatch(string)
    if not match:
        return [], string
    groups = match.groups()
    return groups[:-1], groups[-1]


def extract_all_frame_axtrees(page: playwright.sync_api.Page):
    cdp = page.context.new_cdp_session(page)
    frame_tree = cdp.send("Page.getFrameTree", {})

    frame_ids = []
    frames_to_process = [frame_tree["frameTree"]]
    while frames_to_process:
        frame = frames_to_process.pop()
        frames_to_process.extend(frame.get("childFrames", []))
        frame_ids.append(frame["frame"]["id"])

    frame_axtrees = {
        fid: cdp.send("Accessibility.getFullAXTree", {"frameId": fid})
        for fid in frame_ids
    }

    for ax_tree in frame_axtrees.values():
        for node in ax_tree["nodes"]:
            data_items = []
            if "properties" in node:
                for i, prop in enumerate(node["properties"]):
                    if prop["name"] == "roledescription":
                        data_items, new_value = _extract_data_items_from_aria(prop["value"]["value"])
                        prop["value"]["value"] = new_value
                        if new_value == "":
                            del node["properties"][i]
                        break
            if "description" in node:
                data_items_bis, new_value = _extract_data_items_from_aria(node["description"]["value"])
                node["description"]["value"] = new_value
                if new_value == "":
                    del node["description"]
                if not data_items:
                    data_items = data_items_bis
            if data_items:
                (browsergym_id,) = data_items
                node["browsergym_id"] = browsergym_id

    cdp.detach()
    return frame_axtrees


def extract_merged_axtree(page: playwright.sync_api.Page):
    frame_axtrees = extract_all_frame_axtrees(page)
    cdp = page.context.new_cdp_session(page)

    merged = {"nodes": []}
    for ax_tree in frame_axtrees.values():
        merged["nodes"].extend(ax_tree["nodes"])
        for node in ax_tree["nodes"]:
            if node["role"]["value"] == "Iframe":
                frame_id = (
                    cdp.send("DOM.describeNode", {"backendNodeId": node["backendDOMNodeId"]})
                    .get("node", {})
                    .get("frameId", None)
                )
                if frame_id and frame_id in frame_axtrees:
                    frame_root = frame_axtrees[frame_id]["nodes"][0]
                    node["childIds"].append(frame_root["nodeId"])

    cdp.detach()
    return merged


def extract_focused_element_bid(page: playwright.sync_api.Page) -> str:
    script = """\
() => {
    function getActiveElement(root) {
        const el = root.activeElement;
        if (!el) return null;
        if (el.shadowRoot) return getActiveElement(el.shadowRoot);
        return el;
    }
    return getActiveElement(document);
}"""
    frame = page
    focused_bid = ""
    try:
        while frame:
            elem = frame.evaluate_handle(script, BID_ATTR).as_element()
            if elem:
                frame = elem.content_frame()
                focused_bid = elem.get_attribute(BID_ATTR)
            else:
                frame = None
    except playwright.sync_api.TimeoutError:
        focused_bid = ""
    return focused_bid or ""
