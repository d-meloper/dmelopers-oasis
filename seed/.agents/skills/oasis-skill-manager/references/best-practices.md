# Skill maintenance experience

When moving or shortening a skill, move useful instructions into its reference
before removing the old body, and update consumers and links together. K02's
coverage audit and K41's installed-manual failure show that a list of files is
weaker than working links in a separated installed project. See the
[migration reference](../../../../.oasis/manual/migration-lessons.md).

K29 separates file presence, native discovery and available tools/providers.
All 24 skills are now installed and active. Tool/provider availability still
differs from an installed skill. Local metadata validation checks names and
resources; actual native discovery and model use remain separate checks.

K30 retained acceptance scenarios without claiming live model answers. For a
substantial decision change, a positive, negative or ambiguous scenario can help
review the effect; the expected answer should not be passed as evidence of model
behavior. Short prose and useful references do not require a length or format
compliance checker.

Official skill loading separates initial name/description metadata from full
instructions and supporting references. When keeping many skills available,
lead the description with the actual workflow and load only relevant reference
material. This package's 24 short bodies use that structure; their metadata and
installed links are fixture-checked, without claiming measured model quality.
See [Build skills](https://learn.chatgpt.com/docs/build-skills) and
[official prompting guidance](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra).
