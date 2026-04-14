"""AX tree to string conversion — ported from browsergym.utils.obs.flatten_axtree_to_str."""

IGNORED_AXTREE_ROLES = ["LineBreak"]

IGNORED_AXTREE_PROPERTIES = (
    "editable",
    "readonly",
    "level",
    "settable",
    "multiline",
    "invalid",
    "focusable",
)


def _process_bid(
    bid,
    extra_properties=None,
    with_visible=False,
    with_clickable=False,
    filter_visible_only=False,
):
    if extra_properties is None:
        extra_properties = {}

    skip_element = False
    attributes_to_print = []

    if bid is None:
        if filter_visible_only:
            pass
    elif bid in extra_properties:
        node_vis = extra_properties[bid].get("visibility", 0)
        node_is_clickable = extra_properties[bid].get("clickable", False)
        node_is_visible = node_vis >= 0.5

        if filter_visible_only and not node_is_visible:
            skip_element = True
        if with_visible and node_is_visible:
            attributes_to_print.insert(0, "visible")
        if with_clickable and node_is_clickable:
            attributes_to_print.insert(0, "clickable")

    return skip_element, attributes_to_print


def flatten_axtree_to_str(
    AX_tree,
    extra_properties=None,
    with_visible=False,
    with_clickable=False,
    skip_generic=True,
    filter_visible_only=False,
    ignored_roles=IGNORED_AXTREE_ROLES,
    ignored_properties=IGNORED_AXTREE_PROPERTIES,
    remove_redundant_static_text=True,
) -> str:
    """Formats the accessibility tree into a string text.

    Ported from browsergym.utils.obs.flatten_axtree_to_str to avoid
    numpy/PIL/beautifulsoup dependencies.
    """
    node_id_to_idx = {}
    for idx, node in enumerate(AX_tree["nodes"]):
        node_id_to_idx[node["nodeId"]] = idx

    def dfs(node_idx, depth, parent_node_filtered, parent_node_name):
        tree_str = ""
        node = AX_tree["nodes"][node_idx]
        indent = "\t" * depth
        skip_node = False
        filter_node = False
        node_role = node["role"]["value"]
        node_name = ""

        if node_role in ignored_roles:
            skip_node = True
        elif "name" not in node:
            skip_node = True
        else:
            node_name = node["name"]["value"]
            if "value" in node and "value" in node["value"]:
                node_value = node["value"]["value"]
            else:
                node_value = None

            bid = node.get("browsergym_id", None)

            attributes = []
            for prop in node.get("properties", []):
                if "value" not in prop:
                    continue
                if "value" not in prop["value"]:
                    continue

                prop_name = prop["name"]
                prop_value = prop["value"]["value"]

                if prop_name in ignored_properties:
                    continue
                elif prop_name in ("required", "focused", "atomic"):
                    if prop_value:
                        attributes.append(prop_name)
                else:
                    attributes.append(f"{prop_name}={repr(prop_value)}")

            if skip_generic and node_role == "generic" and not attributes:
                skip_node = True

            if node_role == "StaticText":
                if parent_node_filtered:
                    skip_node = True
                elif remove_redundant_static_text and node_name in parent_node_name:
                    skip_node = True
            else:
                filter_node, extra_attributes = _process_bid(
                    bid,
                    extra_properties=extra_properties,
                    with_visible=with_visible,
                    with_clickable=with_clickable,
                    filter_visible_only=filter_visible_only,
                )
                skip_node = skip_node or filter_node
                attributes = extra_attributes + attributes

            if not skip_node:
                if node_role == "generic" and not node_name:
                    node_str = f"{node_role}"
                else:
                    node_str = f"{node_role} {repr(node_name.strip())}"

                if bid is not None:
                    node_str = f"[{bid}] " + node_str

                if node_value is not None:
                    node_str += f" value={repr(node_value)}"

                if attributes:
                    node_str += ", ".join([""] + attributes)

                tree_str += f"{indent}{node_str}"

        for child_node_id in node["childIds"]:
            if child_node_id not in node_id_to_idx or child_node_id == node["nodeId"]:
                continue
            child_depth = depth if skip_node else (depth + 1)
            child_str = dfs(
                node_id_to_idx[child_node_id],
                child_depth,
                parent_node_filtered=filter_node,
                parent_node_name=node_name,
            )
            if child_str:
                if tree_str:
                    tree_str += "\n"
                tree_str += child_str

        return tree_str

    return dfs(0, 0, False, "")
