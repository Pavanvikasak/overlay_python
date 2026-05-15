#!/usr/bin/env python3
"""Overlay one SVG file on top of another and write the result to a new SVG file."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import streamlit as st
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
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch graphical user interface instead of command line.",
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


def gui_main() -> None:
    if PYQT_AVAILABLE:
        app = QApplication(sys.argv)
        window = SVGOverlayApp()
        window.show()
        sys.exit(app.exec_())
    else:
        # Fallback to tkinter
        root = tk.Tk()
        root.title("SVG Overlay Tool (Tkinter Fallback)")
        root.geometry("1000x600")

        # Variables
        base_path = tk.StringVar()
        overlay_path = tk.StringVar()
        output_path = tk.StringVar()
        x_offset = tk.DoubleVar(value=0.0)
        y_offset = tk.DoubleVar(value=0.0)
        scale = tk.DoubleVar(value=1.0)
        preserve_base_size = tk.BooleanVar(value=True)  # Default to preserve base size
        base_color = tk.StringVar(value="red")
        overlay_color = tk.StringVar(value="green")
        remove_fill = tk.StringVar()

        # Frames
        left_frame = tk.Frame(root, width=500, height=600)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=10, pady=10)
        right_frame = tk.Frame(root, width=500, height=600)
        right_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        # Left: SVG display
        tk.Label(left_frame, text="Output SVG Code:").pack(anchor="w")
        svg_text = tk.Text(left_frame, wrap=tk.WORD, height=30)
        svg_text.pack(fill=tk.BOTH, expand=True)

        def select_base():
            path = filedialog.askopenfilename(filetypes=[("SVG files", "*.svg")])
            if path:
                base_path.set(path)

        def select_overlay():
            path = filedialog.askopenfilename(filetypes=[("SVG files", "*.svg")])
            if path:
                overlay_path.set(path)

        def select_output():
            path = filedialog.asksaveasfilename(defaultextension=".svg", filetypes=[("SVG files", "*.svg")])
            if path:
                output_path.set(path)

        def run_overlay():
            try:
                merge_svgs(
                    Path(base_path.get()),
                    Path(overlay_path.get()),
                    Path(output_path.get()),
                    x_offset.get(),
                    y_offset.get(),
                    scale.get(),
                    preserve_base_size.get(),
                    base_color.get() or None,
                    overlay_color.get() or None,
                    remove_fill.get() or None,
                )
                # Load and display the output SVG
                with open(output_path.get(), 'r', encoding='utf-8') as f:
                    svg_content = f.read()
                svg_text.delete(1.0, tk.END)
                svg_text.insert(tk.END, svg_content)
                messagebox.showinfo("Success", f"Created overlay SVG: {output_path.get()}")
            except Exception as e:
                messagebox.showerror("Error", str(e))

        # Right: Controls
        tk.Label(right_frame, text="Base SVG:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=base_path, width=30).grid(row=0, column=1, padx=10, pady=5)
        tk.Button(right_frame, text="Browse", command=select_base).grid(row=0, column=2, padx=10, pady=5)

        tk.Label(right_frame, text="Overlay SVG:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=overlay_path, width=30).grid(row=1, column=1, padx=10, pady=5)
        tk.Button(right_frame, text="Browse", command=select_overlay).grid(row=1, column=2, padx=10, pady=5)

        tk.Label(right_frame, text="Output SVG:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=output_path, width=30).grid(row=2, column=1, padx=10, pady=5)
        tk.Button(right_frame, text="Browse", command=select_output).grid(row=2, column=2, padx=10, pady=5)

        tk.Label(right_frame, text="X Offset:").grid(row=3, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=x_offset).grid(row=3, column=1, padx=10, pady=5)

        tk.Label(right_frame, text="Y Offset:").grid(row=4, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=y_offset).grid(row=4, column=1, padx=10, pady=5)

        tk.Label(right_frame, text="Scale:").grid(row=5, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=scale).grid(row=5, column=1, padx=10, pady=5)

        tk.Checkbutton(right_frame, text="Preserve Base Size", variable=preserve_base_size).grid(row=6, column=0, columnspan=2, sticky="w", padx=10, pady=5)

        tk.Label(right_frame, text="Base Replace Black Color:").grid(row=7, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=base_color).grid(row=7, column=1, padx=10, pady=5)

        tk.Label(right_frame, text="Overlay Replace Black Color:").grid(row=8, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=overlay_color).grid(row=8, column=1, padx=10, pady=5)

        tk.Label(right_frame, text="Remove Overlay Fill:").grid(row=9, column=0, sticky="w", padx=10, pady=5)
        tk.Entry(right_frame, textvariable=remove_fill).grid(row=9, column=1, padx=10, pady=5)

        tk.Button(right_frame, text="Run Overlay", command=run_overlay, bg="green", fg="white").grid(row=10, column=0, columnspan=3, pady=20)

        root.mainloop()


class SVGOverlayApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SVG Overlay Editor")
        self.setGeometry(100, 100, 1200, 800)

        # Central widget
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # Splitter
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)

        # Left: SVG Viewer
        self.svg_viewer = QSvgWidget()
        self.svg_viewer.setMinimumWidth(600)
        splitter.addWidget(self.svg_viewer)

        # Right: Controls
        controls_widget = QWidget()
        controls_layout = QVBoxLayout(controls_widget)
        splitter.addWidget(controls_widget)

        # Form layout for inputs
        form_layout = QFormLayout()

        self.base_path_edit = QLineEdit()
        self.base_browse_btn = QPushButton("Browse")
        self.base_browse_btn.clicked.connect(self.select_base)
        base_layout = QHBoxLayout()
        base_layout.addWidget(self.base_path_edit)
        base_layout.addWidget(self.base_browse_btn)
        form_layout.addRow("Base SVG:", base_layout)

        self.overlay_path_edit = QLineEdit()
        self.overlay_browse_btn = QPushButton("Browse")
        self.overlay_browse_btn.clicked.connect(self.select_overlay)
        overlay_layout = QHBoxLayout()
        overlay_layout.addWidget(self.overlay_path_edit)
        overlay_layout.addWidget(self.overlay_browse_btn)
        form_layout.addRow("Overlay SVG:", overlay_layout)

        self.output_path_edit = QLineEdit()
        self.output_browse_btn = QPushButton("Browse")
        self.output_browse_btn.clicked.connect(self.select_output)
        output_layout = QHBoxLayout()
        output_layout.addWidget(self.output_path_edit)
        output_layout.addWidget(self.output_browse_btn)
        form_layout.addRow("Output SVG:", output_layout)

        self.x_offset_spin = QDoubleSpinBox()
        self.x_offset_spin.setRange(-1000, 1000)
        self.x_offset_spin.setValue(0.0)
        form_layout.addRow("X Offset:", self.x_offset_spin)

        self.y_offset_spin = QDoubleSpinBox()
        self.y_offset_spin.setRange(-1000, 1000)
        self.y_offset_spin.setValue(0.0)
        form_layout.addRow("Y Offset:", self.y_offset_spin)

        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.1, 10.0)
        self.scale_spin.setValue(1.0)
        self.scale_spin.setSingleStep(0.1)
        form_layout.addRow("Scale:", self.scale_spin)

        self.preserve_size_check = QCheckBox()
        self.preserve_size_check.setChecked(True)  # Default to preserve base size
        form_layout.addRow("Preserve Base Size:", self.preserve_size_check)

        self.base_color_edit = QLineEdit("red")
        form_layout.addRow("Base Replace Black Color:", self.base_color_edit)

        self.overlay_color_edit = QLineEdit("green")
        form_layout.addRow("Overlay Replace Black Color:", self.overlay_color_edit)

        self.remove_fill_edit = QLineEdit()
        form_layout.addRow("Remove Overlay Fill:", self.remove_fill_edit)

        controls_layout.addLayout(form_layout)

        # Run button
        self.run_btn = QPushButton("Run Overlay")
        self.run_btn.setStyleSheet("QPushButton { background-color: green; color: white; font-weight: bold; }")
        self.run_btn.clicked.connect(self.run_overlay)
        controls_layout.addWidget(self.run_btn)

        # SVG Code viewer (below controls)
        self.svg_code_edit = QTextEdit()
        self.svg_code_edit.setMaximumHeight(200)
        controls_layout.addWidget(QLabel("SVG Code:"))
        controls_layout.addWidget(self.svg_code_edit)

    def select_base(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Base SVG", "", "SVG Files (*.svg)")
        if path:
            self.base_path_edit.setText(path)

    def select_overlay(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select Overlay SVG", "", "SVG Files (*.svg)")
        if path:
            self.overlay_path_edit.setText(path)

    def select_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "Select Output SVG", "", "SVG Files (*.svg)")
        if path:
            self.output_path_edit.setText(path)

    def run_overlay(self):
        try:
            output_path = Path(self.output_path_edit.text())
            merge_svgs(
                Path(self.base_path_edit.text()),
                Path(self.overlay_path_edit.text()),
                output_path,
                self.x_offset_spin.value(),
                self.y_offset_spin.value(),
                self.scale_spin.value(),
                self.preserve_size_check.isChecked(),
                self.base_color_edit.text() or None,
                self.overlay_color_edit.text() or None,
                self.remove_fill_edit.text() or None,
            )
            # Load SVG into viewer
            self.svg_viewer.load(str(output_path))
            # Load code
            with open(output_path, 'r', encoding='utf-8') as f:
                self.svg_code_edit.setPlainText(f.read())
            QMessageBox.information(self, "Success", f"Created overlay SVG: {output_path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


def main() -> int:
    args = parse_args()
    if args.gui:
        gui_main()
        return 0
    if not args.base_svg or not args.overlay_svg or not args.output_svg:
        print("Error: base_svg, overlay_svg, and output_svg are required when not using --gui", file=sys.stderr)
        return 1
    try:
        merge_svgs(
            Path(args.base_svg),
            Path(args.overlay_svg),
            Path(args.output_svg),
            args.x,
            args.y,
            args.scale,
            args.preserve_base_size,
            args.base_replace_black_color,
            args.overlay_replace_black_color,
            args.remove_overlay_fill,
        )
    except (FileNotFoundError, ValueError, ET.ParseError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    print(f"Created overlay SVG: {args.output_svg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
