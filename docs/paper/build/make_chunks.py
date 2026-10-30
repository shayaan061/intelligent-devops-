"""Splits the paper's plain text into parts of at most 1,200 words, one paragraph per line.

    python3 docs/paper/build/make_chunks.py docs/paper/EmergIN2027_paperA.txt docs/paper/paperA_chunks [prefix]

Writes <prefix>_part<i>_of_<n>.txt and <prefix>_combinedfinal.txt (prefix default paperA). The .txt from `build_paper.py --txt`
is wrapped at 100 columns; here each paragraph, table row and reference is one line, so tools that
work line by line can't split sentences.
"""
import os
import re
import sys

LIMIT = 1200


def unwrap(block):
    lines = block.splitlines()
    if lines[0].startswith("  ") or lines[0].startswith("TABLE"):          # table rows
        return "\n".join(line.strip() for line in lines)
    if re.match(r"\[\d+\]", lines[0]):                                      # references
        out = []
        for line in lines:
            if re.match(r"\[\d+\]", line.strip()):
                out.append(line.strip())
            else:
                out[-1] += ("" if out[-1].endswith("-") else " ") + line.strip()
        return "\n".join(out)
    if all(len(line) < 60 for line in lines) and not lines[0].startswith("Abstract"):
        return "\n".join(lines)                                             # title, authors
    joined = lines[0]
    for line in lines[1:]:
        # textwrap breaks after hyphens ("re-" / "analyze"); join those without a space
        joined += line if re.search(r"[a-z]-$", joined) and line[:1].islower() else " " + line
    return joined


def main():
    src, out_dir = sys.argv[1], sys.argv[2]
    prefix = sys.argv[3] if len(sys.argv) > 3 else "paperA"
    blocks = [unwrap(b) for b in re.split(r"\n\s*\n", open(src, encoding="utf-8").read().strip())]
    chunks, cur, n = [], [], 0
    for b in blocks:
        w = len(b.split())
        if cur and n + w > LIMIT:
            chunks.append(cur)
            cur, n = [], 0
        cur.append(b)
        n += w
    chunks.append(cur)
    os.makedirs(out_dir, exist_ok=True)
    for name in os.listdir(out_dir):
        if re.match(re.escape(prefix) + r"_part\d+_of_\d+\.txt$", name):
            os.remove(os.path.join(out_dir, name))
    for i, c in enumerate(chunks, 1):
        text = "\n\n".join(c)
        with open(os.path.join(out_dir, f"{prefix}_part{i}_of_{len(chunks)}.txt"), "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"part {i}: {len(text.split())} words")
    with open(os.path.join(out_dir, f"{prefix}_combinedfinal.txt"), "w", encoding="utf-8") as f:
        f.write("\n\n".join(b for c in chunks for b in c) + "\n")


if __name__ == "__main__":
    main()
