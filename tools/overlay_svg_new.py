#!/usr/bin/env python3
"""Overlay one SVG file on top of another and write the result to a new SVG file."""

from __future__ import annotations

import re
import sys
import tempfile
from pathlib import Path

import streamlit as st
from streamlit.components.v1 import html
import xml.etree.ElementTree as ET


SVG_NS = "http://www.w3.org/2000/svg"
ET.register_namespace("", SVG_NS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Overlay one SVG file on top of another and save the combined SVG."
    )
    parser.add_argument("base_svg", nargs='?', help="Base SVG file path")
    parser.add_argument("overlay_svg", nargs='?', help="Overlay SVG file path")
    parser.add_argument("output_svg", nargs='?', help="Output SVG file path")
    parser.add_argument(
        "--x",
        type=float,
        default=0.0,
        help="X offset for the overlay SVG",
    )
    parser.add_argument(
        "--y",
        type=float,
        default=0.0,
        help="Y offset for the overlay SVG",
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help="Scale factor to apply to the overlay SVG",
    )
    parser.add_argument(
        "--preserve-base-size",
        action="store_true",
        help="Keep the base SVG width/height and viewBox instead of using the overlay size",
    )
    parser.add_argument(
        "--base-replace-black-color",
        type=str,
        default="red",
        help=(
            "Replace black fill/stroke values in the base SVG with this color. "
            "Detects #000, #000000, rgb(0,0,0), and black. Default: red"
        ),
    )
    parser.add_argument(
        "--overlay-replace-black-color",
        type=str,
        default="green",
        help=(
            "Replace black fill/stroke values in the overlay SVG with this color. "
            "Detects #000, #000000, rgb(0,0,0), and black. Default: green"
        ),
    )
    parser.add_argument(
        "--remove-overlay-fill",
        type=str,
        default=None,
        help=(
            "Remove elements from overlay SVG that have this fill color. "
            "Useful for removing backgrounds. E.g., 'white', '#FFFFFF', 'none'"
        ),
    )
    return parser.parse_args()


def load_svg(path: Path) -> ET.ElementTree:
    if not path.exists():
        raise FileNotFoundError(f"SVG file not found: {path}")
    return ET.parse(path)


def get_svg_root(tree: ET.ElementTree) -> ET.Element:
    root = tree.getroot()
    if root.tag != f"{{{SVG_NS}}}svg" and not root.tag.endswith("}svg"):
        raise ValueError(f"File does not appear to be an SVG: {root.tag}")
    return root


def copy_children(source: ET.Element, target: ET.Element) -> None:
    for child in list(source):
        source.remove(child)
        target.append(child)


def is_black_color(value: str) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    if normalized == "black":
        return True
    if normalized in {"#000", "#000000"}:
        return True
    if normalized.startswith("rgb(") and normalized.endswith(")"):
        inner = normalized[4:-1].strip()
        parts = [part.strip() for part in inner.split(",")]
        return len(parts) == 3 and all(part == "0" for part in parts)
    return False


def replace_black_color_in_style(style_text: str, color: str) -> str:
    if not style_text:
        return style_text
    parts = style_text.split(";")
    updated = []
    for part in parts:
        if not part.strip():
            continue
        if ":" not in part:
            updated.append(part)
            continue
        key, value = part.split(":", 1)
        if key.strip().lower() in {"fill", "stroke"} and is_black_color(value):
            updated.append(f"{key.strip()}:{color}")
        else:
            updated.append(part)
    return ";".join(updated)


def replace_black_colors(element: ET.Element, color: str) -> None:
    for attribute in ["fill", "stroke"]:
        value = element.get(attribute)
        if value and is_black_color(value):
            element.set(attribute, color)
    style_value = element.get("style")
    if style_value:
        new_style = replace_black_color_in_style(style_value, color)
        element.set("style", new_style)
    for child in list(element):
        replace_black_colors(child, color)


def remove_elements_by_fill(element: ET.Element, fill_color: str, parent: ET.Element | None = None) -> None:
    to_remove = []
    for child in list(element):
        remove_elements_by_fill(child, fill_color, element)
        fill_value = child.get("fill")
        if fill_value and fill_value.lower() == fill_color.lower():
            to_remove.append(child)
            continue
        style_value = child.get("style")
        if style_value:
            style_dict = dict(part.strip().split(":", 1) for part in style_value.split(";") if ":" in part)
            if style_dict.get("fill", "").lower() == fill_color.lower():
                to_remove.append(child)
                continue
    for child in to_remove:
        element.remove(child)


def merge_svgs(base_path: Path, overlay_path: Path, output_path: Path, x: float, y: float, scale: float, preserve_base_size: bool, base_replace_black_color: str | None = None, overlay_replace_black_color: str | None = None, remove_overlay_fill: str | None = None) -> None:
    base_tree = load_svg(base_path)
    overlay_tree = load_svg(overlay_path)

    base_root = get_svg_root(base_tree)
    overlay_root = get_svg_root(overlay_tree)

    if remove_overlay_fill:
        remove_elements_by_fill(overlay_root, remove_overlay_fill)

    if base_replace_black_color:
        replace_black_colors(base_root, base_replace_black_color)
    if overlay_replace_black_color:
        replace_black_colors(overlay_root, overlay_replace_black_color)

    if not preserve_base_size:
        for attr in ["viewBox", "width", "height"]:
            value = overlay_root.get(attr)
            if value is not None:
                base_root.set(attr, value)

    transform_parts = []
    if scale != 1.0:
        transform_parts.append(f"scale({scale})")
    if x or y:
        transform_parts.append(f"translate({x} {y})")
    transform = " ".join(transform_parts) if transform_parts else None

    wrapper = ET.Element(f"{{{SVG_NS}}}g")
    if transform:
        wrapper.set("transform", transform)

    copy_children(overlay_root, wrapper)

    base_root.append(wrapper)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_tree.write(output_path, encoding="utf-8", xml_declaration=True)


def sanitize_svg_for_html(svg_content: str) -> str:
    svg_text = re.sub(r"^<\?xml[^>]*>\s*", "", svg_content, flags=re.IGNORECASE)
    svg_text = svg_text.strip()
    return svg_text


def streamlit_app():
    st.title("SVG Overlay Tool")

    st.sidebar.header("Settings")

    base_file = st.sidebar.file_uploader("Base SVG", type=["svg"])
    overlay_file = st.sidebar.file_uploader("Overlay SVG", type=["svg"])

    x = st.sidebar.slider("X Offset", -1000, 1000, 0)
    y = st.sidebar.slider("Y Offset", -1000, 1000, 0)
    scale = st.sidebar.slider("Scale", 0.1, 10.0, 1.0, 0.1)
    preserve = st.sidebar.checkbox("Preserve Base Size", value=True)
    base_color = st.sidebar.text_input("Base Replace Black Color", "red")
    overlay_color = st.sidebar.text_input("Overlay Replace Black Color", "green")
    remove_fill = st.sidebar.text_input("Remove Overlay Fill")

    if st.sidebar.button("Generate Overlay") and base_file and overlay_file:
        with st.spinner("Processing..."):
            try:
                # Save uploaded files to temp
                with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
                    f.write(base_file.read())
                    base_path = f.name
                with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
                    f.write(overlay_file.read())
                    overlay_path = f.name
                output_path = tempfile.mktemp(suffix=".svg")

                merge_svgs(
                    Path(base_path),
                    Path(overlay_path),
                    Path(output_path),
                    x,
                    y,
                    scale,
                    preserve,
                    base_color or None,
                    overlay_color or None,
                    remove_fill or None,
                )

                with open(output_path, "r", encoding="utf-8") as f:
                    svg_content = f.read()

                st.success("Overlay generated!")

                # Display SVG
                st.subheader("Output SVG")
                svg_display = sanitize_svg_for_html(svg_content)
                html(f'<div style="text-align: center;">{svg_display}</div>', height=600)

                # Code
                st.subheader("SVG Code")
                st.code(svg_content, language="xml")

                # Download
                st.download_button("Download SVG", svg_content, file_name="overlay.svg", mime="image/svg+xml")
            except Exception as e:
                st.error(f"Error generating overlay: {str(e)}")


if __name__ == "__main__":
    streamlit_app()