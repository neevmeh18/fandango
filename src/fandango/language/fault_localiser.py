# fault_localiser.py
from fandango.language.parse import parse
from fandango.language.grammar.nodes.non_terminal import NonTerminal
from fandango.language.grammar.node_visitors.symbol_finder import SymbolFinder
from collections import Counter, defaultdict
import pandas as pd
import math
import subprocess

WEIGHT_FINISHED = 1
WEIGHT_PARTIAL = 3
WEIGHT_NOT_STARTED = 2

# === Load grammar ===
non_terminals = set()
with open("list_grammar.fan", "r") as file:
    for line in file:
        if "::=" in line:
            lhs = line.split("::=")[0].strip()
            non_terminals.add(NonTerminal(lhs))

with open("list_grammar.fan", "r") as f:
    grammar, constraints = parse(f, parties=["Client", "Server"])

test_inputs = [

# 1. USER ok (+OK\r\n), PASS ok (+OK <text>), LIST multi-line (2 entries), QUIT ok (+OK <text>)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 2. USER ok, PASS fail (-ERR ...), LIST rejected, QUIT rejected
"+OK Hello there\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Invalid password\r\nLIST\r\n-ERR Not logged in\r\nQUIT\r\n-ERR Session not started\r\n",

# 3. USER rejected (-ERR ...), PASS ok (+OK <text>), LIST single-line response, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Bad user\r\nPASS NEWpass123\r\n+OK Proceed\r\nLIST\r\n+OK 2 messages\r\nQUIT\r\n+OK End\r\n",

# 4. USER ok, PASS ok (+OK <text>), LIST with +OK alone (positive_response_alone), QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK\r\nQUIT\r\n+OK Completed\r\n",

# 5. USER ok, PASS error (-ERR ...), LIST error, QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Wrong pass\r\nLIST\r\n-ERR Not allowed\r\nQUIT\r\n-ERR Quit denied\r\n",

# 6. USER ok, PASS ok, LIST with message number success (LIST 5), QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST 5\r\n+OK Message 5 is 320 octets\r\nQUIT\r\n+OK Done\r\n",

# 7. USER ok, PASS ok, LIST with message number negative response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST 3\r\n-ERR No such message\r\nQUIT\r\n+OK Exit\r\n",

# 8. USER ok, PASS ok, LIST multi-line with only one entry, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK Mailbox scan\r\n1 123\r\n.\r\nQUIT\r\n+OK Terminated\r\n",

# 9. USER error, PASS error, LIST multi-line empty (just terminator), QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Unknown user\r\nPASS NEWpass123\r\n-ERR Blocked\r\nLIST\r\n+OK Mailbox is empty\r\n.\r\nQUIT\r\n-ERR Quit failed\r\n",

# 10. USER ok, PASS ok, LIST ok single-line, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK All good\r\nLIST\r\n+OK 1 message\r\nQUIT\r\n+OK See you\r\n"

]


# === Collect spectra ===
spectra_rows = []
for inp in test_inputs:
    tree = grammar.parse(inp)
    parsed = tree is not None
    spectra = grammar._parser._iter_parser.spectra

    complete_counter = Counter(spectra["finished"])
    incomplete_counter = Counter(spectra["incomplete"] - spectra["finished"])
    not_started_counter = Counter(spectra["predicted"] - spectra["finished"] - spectra["incomplete"])

    row = {"input": inp, "parsed": parsed}
    for rule in non_terminals:
        score = 0
        score += complete_counter.get(rule, 0) * WEIGHT_FINISHED
        score += incomplete_counter.get(rule, 0) * WEIGHT_PARTIAL
        score += not_started_counter.get(rule, 0) * WEIGHT_NOT_STARTED
        row[rule.format_as_spec()] = score
    spectra_rows.append(row)

df = pd.DataFrame(spectra_rows)

# === Suspiciousness metrics ===
def tarantula(p, f, P, F):
    if (p + f) == 0 or P == 0 or F == 0: return 0.0
    return (f / F) / ((f / F) + (p / P))

def ochiai(p, f, P, F):
    denom = math.sqrt((f + p) * F)
    return f / denom if denom > 0 else 0.0

def dstar(p, f, P, F, n=2):
    denom = p + (F - f)
    return (f**n) / denom if denom > 0 else float("inf")

total_pass = df[df["parsed"] == True].shape[0]
total_fail = df[df["parsed"] == False].shape[0]

rule_cols = [rule.format_as_spec() for rule in non_terminals]

# === Variant 1: Raw ===
def compute_raw():
    stats = []
    for rule in rule_cols:
        p_score = df[df["parsed"] == True][rule].sum()
        f_score = df[df["parsed"] == False][rule].sum()
        stats.append({
            "rule": rule,
            "raw_pass": p_score,
            "raw_fail": f_score,
            "ochiai_raw": ochiai(p_score, f_score, total_pass, total_fail),
        })
    return pd.DataFrame(stats)

# === Variant 2: Normalised ===
def compute_norm():
    df_norm = df.copy()
    df_norm[rule_cols] = df_norm[rule_cols].astype(float)
    row_sums = df_norm[rule_cols].sum(axis=1)
    df_norm[rule_cols] = df_norm[rule_cols].div(row_sums, axis=0).fillna(0.0)

    stats = []
    for rule in rule_cols:
        p_score = df_norm[df_norm["parsed"] == True][rule].sum()
        f_score = df_norm[df_norm["parsed"] == False][rule].sum()
        stats.append({
            "rule": rule,
            "norm_pass": p_score,
            "norm_fail": f_score,
            "ochiai_norm": ochiai(p_score, f_score, total_pass, total_fail),
        })
    return pd.DataFrame(stats)

# === Variant 3: IDF + Leaf Penalty ===
def compute_idf():
    rule_doc_freq = {
        rule: sum((row[rule] > 0) for _, row in df.iterrows())
        for rule in rule_cols
    }
    def idf_penalty(rule):
        return math.log(1 + len(df) / (1 + rule_doc_freq[rule]))



    stats = []
    for rule in rule_cols:
        p_score = df[df["parsed"] == True][rule].sum()
        f_score = df[df["parsed"] == False][rule].sum()
        penalty = idf_penalty(rule)

        p_scaled = (p_score / penalty)
        f_scaled = (f_score / penalty)
        stats.append({
            "rule": rule,
            "idf_pass": p_scaled,
            "idf_fail": f_scaled,
            "ochiai_idf": ochiai(p_scaled, f_scaled, total_pass, total_fail),
        })
    return pd.DataFrame(stats)

# === Combine ===
df_raw = compute_raw()
df_norm_stats = compute_norm()
df_idf = compute_idf()
combined = df_raw.merge(df_norm_stats, on="rule").merge(df_idf, on="rule")
combined = combined.sort_values(by="ochiai_idf", ascending=False)

print("\n=== Suspiciousness Comparison (Raw / Normalised / IDF) ===")
print(combined[[
    "rule",
    "ochiai_raw","ochiai_norm","ochiai_idf",
    "raw_fail","norm_fail","idf_fail",
    "raw_pass","norm_pass","idf_pass"
]])
def compute_roles_downward(grammar):
    roles_map = defaultdict(set)

    # Step 1: Collect direct annotations
    for nt, rule in grammar.rules.items():
        finder = SymbolFinder()
        finder.visit(rule)
        for nt_node in finder.nonTerminalNodes:
            target = nt_node.symbol
            if nt_node.sender:
                roles_map[target].add(nt_node.sender)
            if nt_node.recipient:
                roles_map[target].add(nt_node.recipient)

    # Step 2: Downward propagation
    changed = True
    while changed:
        changed = False
        for nt, rule in grammar.rules.items():
            parent_roles = roles_map.get(nt, set())
            if not parent_roles:
                continue
            finder = SymbolFinder()
            finder.visit(rule)
            for nt_node in finder.nonTerminalNodes:
                child = nt_node.symbol
                before = roles_map.get(child, set()).copy()
                roles_map[child] |= parent_roles
                if roles_map[child] != before:
                    changed = True

    # Step 3: Collapse initial roles
    final_roles = {}
    for nt in grammar.rules:
        roles = roles_map.get(nt, set())
        if len(roles) == 1:
            final_roles[nt.format_as_spec()] = list(roles)[0]
        elif len(roles) > 1:
            final_roles[nt.format_as_spec()] = "Neutral"
        else:
            final_roles[nt.format_as_spec()] = None  # still unknown

    # Step 4: Upward filling from children
    changed = True
    while changed:
        changed = False
        for nt, rule in grammar.rules.items():
            key = nt.format_as_spec()
            if final_roles[key] is None:
                finder = SymbolFinder()
                finder.visit(rule)
                child_roles = {final_roles.get(ch.symbol.format_as_spec())
                               for ch in finder.nonTerminalNodes}

                if None in child_roles:
                    continue  # wait until children stabilise

                non_neutral = {r for r in child_roles if r != "Neutral"}
                if len(non_neutral) == 1 and len(child_roles) == 1:
                    # all children are the same concrete role (Server or Client)
                    final_roles[key] = list(non_neutral)[0]
                    changed = True
                # else → leave it for later (will default to Neutral)

    # Step 5: Default leftover → Neutral
    for nt in grammar.rules:
        key = nt.format_as_spec()
        if final_roles[key] is None:
            final_roles[key] = "Neutral"

    return final_roles



# === Streaming execution ===
def run_fandango_stream(fan_file, port=25110, log_file="fandango_session.log"):
    cmd = ["fandango", "-v", "talk", "--infinite", "-f", fan_file, "--client", str(port)]
    print(f"\n[run_fandango_stream] Running: {' '.join(cmd)}")

    error_signals = []
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc, open(log_file, "w") as lf:
            for line in proc.stdout:
                line = line.strip()
                lf.write(line + "\n")
                print("FANDANGO:", line)
                if "Could not parse received message fragments into predicted NonTerminals" in line:
                    error_signals.append({"type": "server_error", "line": line})
                if "fandango:INFO: Server:" in line and "-ERR Unknown command" in line:
                    error_signals.append({"type": "client_error", "line": line})
    except KeyboardInterrupt:
        print("\n[run_fandango_stream] Interrupted by user.")
    except Exception as e:
        print(f"\n[run_fandango_stream] Error: {e}")
    return error_signals

# === Role-based filtering ===
def apply_role_filtering(df_scores, grammar, signals, variant="ochiai_idf"):
    roles_lookup = compute_roles_downward(grammar)
    server_side = any(sig["type"] == "server_error" for sig in signals)
    client_side = any(sig["type"] == "client_error" for sig in signals)

    adjusted = df_scores.copy()
    adjusted["role"] = adjusted["rule"].map(lambda r: roles_lookup.get(r, "Neutral"))

    def adjust(row):
        role = row["role"]
        if role == "Server":
            return 0.0 if client_side else row[variant]
        elif role == "Client":
            return 0.0 if server_side else row[variant]
        else:
            return row[variant] * 0.5 

    adjusted[f"{variant}_filtered"] = adjusted.apply(adjust, axis=1)
    return adjusted.sort_values(by=f"{variant}_filtered", ascending=False)

# === Execute ===
fan_file = "list_grammar.fan"
signals = run_fandango_stream(fan_file, port=25110)

print("\n=== Collected Error Signals ===")
for sig in signals: print(sig["type"], "->", sig["line"])

filtered_df = apply_role_filtering(combined, grammar, signals, variant="ochiai_idf")
print("\n=== Ranked Suspicious Rules (Role-Filtered, using Ochiai+IDF) ===")
print(filtered_df)
