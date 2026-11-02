#!/usr/bin/env python3

import sys

source_path, destination_path, executable_path = sys.argv[1:]
escaped_executable = executable_path.replace("\\", "\\\\").replace('"', '\\"')

with open(source_path, encoding="utf-8") as source:
    lines = source.readlines()

for index, line in enumerate(lines):
    if line.startswith("Exec="):
        lines[index] = f'Exec="{escaped_executable}"\n'
        break
else:
    raise ValueError(f"No Exec entry found in {source_path}")

with open(destination_path, "w", encoding="utf-8") as destination:
    destination.writelines(lines)
