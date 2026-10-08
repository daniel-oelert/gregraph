# Built-in templates (package data, spec §16.1, §16.4)

Shipped template directories live here as `<name>/v1/template.md` and
`<name>/v1/template.json` (spec §5.5, appendix B.2). `gregraph init` and
`gregraph template add` copy them into `.gregraph/templates/` (spec §13.1,
§13.17).

The 14 shipped `v1` templates (appendix B.2): `context`, `goal`, `epic`,
`feature`, `user-story`, `requirement-ears`, `constraint`, `design`, `decision`,
`test-case`, `stakeholder`, `assumption`, `change-request`, `term`.

`template.md` starts with `# {{ title }}`, then each section as `## Heading`
with its placeholder on the next line in *italics* (variables are used only for
the H1). `template.json` is the canonical-JSON descriptor validated by
`gregraph.core.models.TemplateDescriptor`. Golden tests:
`tests/test_builtin_templates.py`.
