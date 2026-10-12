"""Strip comments from strings: dialects, blank lines, code protection, escaping.

    python examples/01_strip_basics.py
"""

from prompt_comments import strip_comments

prompt = """\
You are a helpful support assistant. {# keep tone friendly, not robotic #}
Always answer in the user's language. <!-- TODO: revisit for RTL languages -->

// internal: legal reviewed this paragraph on 2025-03-01
Never promise refunds.
"""

print("== default dialect ({# #}, <!-- -->, //) ==")
print(repr(strip_comments(prompt)))

print("\n== blank_lines='comment': drop only the lines a comment emptied ==")
print(repr(strip_comments(prompt, blank_lines="comment")))

print("\n== other dialects ==")
print(repr(strip_comments("model: gpt  # pinned for evals", dialect="yaml")))
print(repr(strip_comments("a {# x #} b # y", dialect=["jinja", "python"])))

print("\n== code blocks and `inline code` are left alone ==")
doc = "Explain this: // drop me\n```js\nconst x = 1; // KEEP\n```\nUse `a // b` as-is."
print(strip_comments(doc))

print("\n== escaping a literal marker ==")
print(strip_comments(r"Meet in room \//3 // but not this", dialect="default"))
