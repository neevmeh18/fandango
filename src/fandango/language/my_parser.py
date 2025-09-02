from fandango.language.parse import parse
from fandango.language.grammar.nodes.non_terminal import NonTerminal
from collections import Counter
from fandango.language.my_constraint_checker import evaluate_constraints


import math
import pandas as pd



WEIGHT_FINISHED = 1
WEIGHT_PARTIAL = 3
WEIGHT_NOT_STARTED = 2

non_terminals = set()
with open('list_grammar.fan', 'r') as file:
    for line in file:
        line = line.strip()
        if '::=' in line:
            lhs = line.split('::=')[0].strip()
            non_terminals.add(NonTerminal(f'{lhs}'))



with open('list_grammar.fan', 'r') as f:
    grammar, constraints = parse(f)

test_inputs_pass = [

# 1. Successful login, LIST with multi-line response, QUIT with +OK <text>
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST\r\n+OK Scan listing follows\r\n1 120\r\n2 456\r\n.\r\nQUIT\r\n+OK Bye\r\n",

# 2. Invalid password, LIST not allowed, QUIT with error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Invalid password\r\nLIST\r\n-ERR Not logged in\r\nQUIT\r\n-ERR Session not started\r\n",

# 3. USER rejected, PASS succeeds anyway, LIST with single line response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Bad user\r\nPASS NEWpass123\r\n+OK Proceed\r\nLIST\r\n+OK 2 messages\r\nQUIT\r\n+OK End\r\n",

# 4. USER ok, PASS ok (bare +OK\r\n), LIST with +OK alone, QUIT success
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK\r\nQUIT\r\n+OK Completed\r\n",

# 5. USER ok, PASS error, LIST error, QUIT error
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n-ERR Wrong pass\r\nLIST\r\n-ERR Not allowed\r\nQUIT\r\n-ERR Quit denied\r\n",

# 6. LIST with message number (valid, between 1 and 10)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK Logged in\r\nLIST 5\r\n+OK Message 5 is 320 octets\r\nQUIT\r\n+OK Done\r\n",

# 7. LIST with message number, negative response
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST 3\r\n-ERR No such message\r\nQUIT\r\n+OK Exit\r\n",

# 8. LIST multi-line with only one message
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK text\r\nLIST\r\n+OK Mailbox scan\r\n1 123\r\n.\r\nQUIT\r\n+OK Terminated\r\n",

# 9. USER error, PASS error, LIST multi-line empty (just terminator)
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n-ERR Unknown user\r\nPASS NEWpass123\r\n-ERR Blocked\r\nLIST\r\n+OK Mailbox is empty\r\n.\r\nQUIT\r\n-ERR Quit failed\r\n",

# 10. USER ok, PASS ok, LIST ok single line, QUIT ok
"+OK POP3 server ready\r\nUSER debug@localdomain.test\r\n+OK\r\nPASS NEWpass123\r\n+OK All good\r\nLIST\r\n+OK 1 message\r\nQUIT\r\n+OK See you\r\n"

]






test_inputs_fail = []


# Container for grammar spectra and constraint results
spectra_rows = []
constraint_analysis = []

def process_input(raw_input: str):
    tree = grammar.parse(raw_input)
    spectra = grammar._parser.spectra
    nt_role_map = {}
    for nt in grammar.rules:
        roles = grammar[nt].tree_roles(grammar, include_recipients=True)
        recipients = grammar[nt].tree_roles(grammar, include_recipients=True) - roles
        nt_role_map[nt] = (roles, recipients)

    #print("Roles & recipients per NonTerminal in spectra:")
    for category, nts in spectra.items():  # 'finished', 'predicted', 'incomplete'
        #print(f"\n[{category}]")
        for nt in nts:
            roles, recipients = nt_role_map.get(nt, (set(), set()))
            #print(f"{nt}: roles={roles or None}, recipients={recipients or None}")

    max_position = grammar._parser.max_position()
    if tree is None:
        print(max_position)
    else:
        print("Success")

    used_rules = spectra['finished'] + spectra['predicted']
    c1 = Counter(spectra['incomplete'])
    c2 = Counter(spectra['finished'])
    c3 = Counter(used_rules)

    incomplete_counter = c1 - c2
    not_started_counter = c3 - c1 - c2

    spectra_rows.append({
        'input': raw_input,
        'parsed': tree is not None,
        'used_rules': used_rules,
        'incomplete_rules': list(incomplete_counter.elements()),
        'complete_rules': spectra['finished'],
        'not_started_rules': list(not_started_counter.elements())
    })

    if tree is not None:
        constraint_analysis.append(evaluate_constraints(tree, constraints))
    else:
        constraint_analysis.append([])
    return tree

# Run both test suites
paths = []
for inp in test_inputs_pass:
    
    process_input(inp)



weighted_coverage = []

for row in spectra_rows:
    coverage = {
    'input': row['input'],
    'parsed': row['parsed'],
    }
    # Convert lists to Counters to get rule frequencies
    complete_counter = Counter(row.get('complete_rules', []))
    incomplete_counter = Counter(row.get('incomplete_rules', []))
    not_started_counter = Counter(row.get('not_started_rules', []))

    for rule in non_terminals:
        score = 0
        score += complete_counter.get(rule, 0) * WEIGHT_FINISHED
        score += incomplete_counter.get(rule, 0) * WEIGHT_PARTIAL
        score += not_started_counter.get(rule, 0) * WEIGHT_NOT_STARTED

        coverage[str(rule)] = score  # include 0 scores too
    weighted_coverage.append(coverage)
df = pd.DataFrame(weighted_coverage)



# Step 2: Metric functions (unchanged)
def tarantula(p, f, P, F):
    if (p + f) == 0 or P == 0 or F == 0:
        return 0.0
    return (f / F) / ((f / F) + (p / P))

def ochiai(p, f, P, F):
    denom = math.sqrt((f + p) * F)
    if denom == 0:
        return 0.0
    return f / denom

def dstar(p, f, P, F, n=2):
    denom = p + (F - f)
    if denom == 0:
        return float('inf')
    return (f ** n) / denom

total_pass = df[df['parsed'] == True].shape[0]
total_fail = df[df['parsed'] == False].shape[0]

stats = []
for rule in non_terminals:
    rule = str(rule)
    p_score = df[df['parsed'] == True][rule].sum()
    f_score = df[df['parsed'] == False][rule].sum()
    stats.append({
        'rule': rule,
        'weighted_pass': p_score,
        'weighted_fail': f_score,
        'tarantula': tarantula(p_score, f_score, total_pass, total_fail),
        'ochiai': ochiai(p_score, f_score, total_pass, total_fail),
        'dstar': dstar(p_score, f_score, total_pass, total_fail)
    })

stats_df = pd.DataFrame(stats)
df_norm = df.copy()

# Normalize all rule columns (excluding 'input' and 'parsed')
rule_cols = [str(rule) for rule in non_terminals]
df_norm[rule_cols] = df_norm[rule_cols].astype(float)
for index, row in df.iterrows():
    total = sum(row[rule] for rule in rule_cols)
    for rule in rule_cols:
        df_norm.at[index, rule] = float(row[rule]) / total if total > 0 else 0.0


stats_norm = []
for rule in non_terminals:
    rule = str(rule)
    p_score = df_norm[df_norm['parsed'] == True][rule].sum()
    f_score = df_norm[df_norm['parsed'] == False][rule].sum()
    stats_norm.append({
        'rule': rule,
        'weighted_pass_norm': p_score,
        'weighted_fail_norm': f_score,
        'tarantula_norm': tarantula(p_score, f_score, total_pass, total_fail),
        'ochiai_norm': ochiai(p_score, f_score, total_pass, total_fail),
        'dstar_norm': dstar(p_score, f_score, total_pass, total_fail)
    })

stats_norm_df = pd.DataFrame(stats_norm)

combined_df = stats_df.merge(stats_norm_df, on='rule')

print("total_pass: ", total_pass, "total_fail: ", total_fail)

print(combined_df.sort_values(by='ochiai_norm', ascending=False))


for input_index, input_results in enumerate(constraint_analysis):
    print(f"\n=== Constraint Analysis for Input #{input_index + 1} ===")
    for res in input_results:
        print(f"[{res['index']}] Constraint: {res['constraint']}")
        print(f"  Status: {res['status'].upper()} ({res['solved']}/{res['total']})")
        
        if res["status"] == "failed":
            for ft in res["failing_trees"]:
                print(f"    ⛔ Failed at tree: {ft['tree']}")
                for s in ft["suggestions"]:
                    print(f"      ↳ Suggestion: change {s['side']} to {s['value']} ({s['operator']})")
        
        elif res["status"] == "error":
            print(f"  ⚠️ Error: {res['error']}")
    print("=== End of Analysis ===\n")


