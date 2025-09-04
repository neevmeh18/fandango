<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <user_exchange> <pass_exchange>
<transaction_exchanges> ::= <stat_exchange>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

<user_exchange> ::= <Client:USER> <Server:user_response>
<pass_exchange> ::= <Client:PASS> <Server:pass_response>
<stat_exchange> ::= <Client:STAT> <Server:stat_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> <username> <crlf>
<PASS> ::= "PASS" <space> <password> <crlf>
<STAT> ::= "STAT" <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response> | <negative_response>
<positive_response> ::= '+OK' <space>* <text>* <crlf>
<pass_response> ::= <positive_response> | <negative_response>
<stat_response> ::= <positive_response>
<quit_response> ::= <positive_response> (<text> <crlf>)+ #$$$$$$$$extra 2 nonterminals


<negative_response> ::= "-ERR" <space> <text> <crlf>

# ---- TERMINALS ----
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"

# ---- CONSTRAINTS ----
<username> ::= "debug@localdomain.test"
<password> ::= "NEWpass123"