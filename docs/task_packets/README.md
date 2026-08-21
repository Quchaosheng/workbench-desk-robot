# Task Packets

Every bounded AI-assisted or human task starts with an owner, allowed paths, acceptance commands and evidence. The foundation validates JSON packets today; the team may add YAML support after pinning a YAML parser.

With `--base`, the validator checks Git-visible changed paths against one packet. It is a consistency gate, not a filesystem sandbox: ignored build/runtime files are outside its scope, and human approval still comes from protected-branch review. Command checks recognize evidence-tool syntax but never execute or prove that an interpreter's arguments are safe.
