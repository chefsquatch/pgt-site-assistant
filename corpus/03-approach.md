# How PGT Approaches the Work

PGT's whole reason to exist is that AI-assisted development is unreliable by
default, and most teams try to fix it with more prompting or more guardrails
bolted on top. PGT's stance is that this is a **process and diagnosis** problem,
not a prompt-tweak problem.

The method, stated at the level the public site describes:
- **Diagnosis first.** Find where the failures actually originate — is it the
  prompts, the context management, the process, or the tooling? Guessing at the
  fix without locating the source is how teams stay stuck.
- **Then a disciplined process.** Rebuild the workflow into one that ships
  accurate code the first time, and hand it to the team so they keep it. The goal
  is that the team is more reliable after PGT leaves, not dependent on PGT.
- **Proof over claims.** PGT ships real, running software and open source rather
  than slideware. The demos on the site are the argument.
- **Nothing ships until it's right.** Reliability is the product, so correctness
  is not negotiable — including for this very assistant.

What "reliability" concretely means here: AI and software that does not drift off
the task, does not hallucinate facts or APIs, and does not produce output the
user didn't ask for. When PGT builds an AI feature, honesty about the limits of
what the AI knows is built in — the way this assistant refuses to guess, and the
way the RAG demo says "not in the documents" instead of inventing an answer.
