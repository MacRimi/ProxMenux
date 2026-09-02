"""Standardized test prompt for ProxMenux AI-model verification.

Mirrors the real AI-enrichment use case: take a raw Proxmox system
notification (English, with technical identifiers), translate it into
Spanish, explain in plain terms, and suggest one concrete action. It is
intentionally simple — if a model can't do this, it won't do the real
thing either. Models that pass this test are fine for inclusion in
verified_ai_models.json.
"""

SYSTEM_PROMPT = (
    "You are a Proxmox system-notification assistant. "
    "When given a raw notification from a Proxmox host, you: "
    "(1) translate it into Spanish, "
    "(2) explain in 2-3 sentences what the user is seeing and the likely cause, "
    "(3) suggest ONE concrete next action. "
    "Keep technical identifiers (device paths like /dev/sdd, SMART keywords, "
    "ata port numbers, BDFs) in their original form. "
    "Respond only in Spanish. Stay under 200 tokens total."
)

# Realistic ProxMenux notification payload: multi-line body with
# SMART/ATA vocabulary and a frequency hint — the exact shape the real
# pipeline emits.
USER_MESSAGE = (
    "Event: disk_io_error\n"
    "Severity: CRITICAL\n"
    "Host: pve-constructor\n"
    "Device: /dev/sdd\n"
    "SMART status: PASSED\n"
    "Summary: 3 I/O event(s) in 5 minutes, disk passed SMART short test\n"
    "Sample kernel line: ata4.00: exception Emask 0x0 SAct 0x804000 SErr 0x0 action 0x6\n"
    "Frequency: 3 occurrences in 24h, first seen 6h ago"
)

# Common Spanish stopwords. A response missing ALL of these is almost
# certainly not Spanish (or empty/truncated). Cheap heuristic, good
# enough for a coarse pass/fail.
REQUIRED_SPANISH_HINTS = [
    " el ", " la ", " los ", " las ", " un ", " una ",
    " de ", " del ", " en ", " con ", " que ", " para ",
    " es ", " se ", " ha ", " por ", " y ",
]

# Domain keywords — at least one must appear to confirm the model
# actually engaged with the notification instead of replying generically.
DOMAIN_HINTS = [
    "disco", "sdd", "smart", "ata", "i/o", "e/s", "error",
    "kernel", "proxmox",
]
