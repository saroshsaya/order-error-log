"""Shared constants: sheet columns, dropdown vocabularies and the points rules."""

COLUMNS = [
    "submitted_at",      # when Submit was pressed (IST)
    "logged_by",
    "date_reported",     # date the error was detected / reported
    "how_caught",
    "order_id",
    "packed_at",         # packing timestamp (TGS) from Samasya - errors are counted in this month
    "packer",
    "assembler",
    "category",          # Internal / External / Unknown
    "reason",
    "drugs_affected",    # DC codes, free text
    "mistakes",          # number of drugs / items wrong
    "packer_points",
    "assembler_points",
    "description",
    "reversed",          # "Yes" once an appeal succeeds - row stays, points stop counting
    "reversed_reason",
    "reversed_on",
    "needs_review",      # set by the history import when unsure
]

CATEGORIES = ["Internal", "External", "Unknown"]

HOW_CAUGHT = [
    "Customer complaint",
    "Pickup exception",
    "Restocking check (RTO / DTO / cancelled)",
    "Reported by packer at packing",
]
IMPORTED = "Imported from old sheet"

# reason -> points per mistake for (assembler, packer); fixed=True means once per order (labels)
# Internal: verified on camera, we made the mistake. Unknown: couldn't verify -> nobody penalised.
REASONS = {
    "Internal": {
        "Wrong drug packed":                          {"a": 1, "p": 1},
        "Missing quantity":                           {"a": 1, "p": 1},
        "Extra quantity":                             {"a": 1, "p": 1},
        "Outer box not opened to check":              {"a": 1, "p": 1},
        "Assembly error caught by packer at packing": {"a": 1, "p": 0},
        "Wrong label / wrong order labelled":         {"a": 0, "p": 2, "fixed": True},
        "Non-English address not held back":          {"a": 0, "p": 2, "fixed": True},
        "Other internal":                             {"a": 1, "p": 1},
        "Internal - reason not recorded (old data)":  {"a": 1, "p": 1},
    },
    "External": {
        "Packed correctly - footage checked": {"a": 0, "p": 0},
        "Damaged / lost in transit":          {"a": 0, "p": 0},
        "Other external":                     {"a": 0, "p": 0},
    },
    "Unknown": {
        "Packed / assembled out of camera view":     {"a": 0, "p": 0},
        "Footage not found":                         {"a": 0, "p": 0},
        "History not found":                         {"a": 0, "p": 0},
        "Footage not clear":                         {"a": 0, "p": 0},
        "Items not visible (not taken out of box)":  {"a": 0, "p": 0},
    },
}


def rule(category, reason):
    return REASONS.get(category, {}).get(reason, {"a": 0, "p": 0})


def is_fixed(category, reason):
    return bool(rule(category, reason).get("fixed"))


def points(category, reason, mistakes):
    """-> (packer_points, assembler_points). Labels count once per order."""
    r = rule(category, reason)
    n = 1 if r.get("fixed") else max(int(mistakes or 1), 1)
    return r["p"] * n, r["a"] * n


# login -> display name (copied from the efficiency dashboard's config.py; add new people here)
LOGIN_NAMES = {
    "naagard47@gmail.com": "Deepak",
    "panindia135@gmail.com": "Vijay",
    "sunilkumar19902015@gmail.com": "Sunil",
    "kumarritik48822@gmail.com": "Ritik",
    "mohitpatel639049@gmail.com": "Mohit",
    "deepak86650@gmail.com": "Devendra",
    "jitindersingh9720@gmail.com": "Jitendra",
    "lexor0001@gmail.com": "Sahil",
    "ks1354933@gmail.com": "Kartik",
    "akashk00525@gmail.com": "Akash",
    "sunnyrajak618@gmail.com": "Sunny",
    "naduraj4848@gmail.com": "Nandu",
    "nanduraj4848@gmail.com": "Nandu",
    "dmg@saya.net.in": "Dhruv",
    "ay9936370@gmail.com": "Anurag",
}

START_DATE = "2026-01-01"       # error % is calculated for orders packed from this date
LOW_VOLUME = 500                # people with fewer orders in the period are marked "low volume"
