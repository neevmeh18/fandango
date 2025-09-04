<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <user_exchange> <pass_exchange>
<user_exchange> ::= <Client:USER> <Server:user_response>
<pass_exchange> ::= <Client:PASS> <Server:pass_response>
<transaction_exchanges> ::= <dele_exchange>
<dele_exchange> ::= <Client:DELE> <Server:dele_response>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> <username> <crlf>
<PASS> ::= "PASS" <space> <password> <crlf>
<DELE> ::= "DELE" <space> <message_number> <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response> | <negative_response>
<pass_response> ::= <positive_response> | <negative_response>
<dele_response> ::= <positive_response> | <negative_response>
<quit_response> ::= <positive_response> | <negative_response>

<positive_response> ::= "+OK" <space> <text> <crlf>
<negative_response> ::= "-ERR" <space> <text> <crlf>

# ---- TERMINALS ----
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"

# ---- REUSABLE TERMINALS ----
<username> ::= "debug@localdomain.test"
<password> ::= "NEWpass123"
<message_number> ::= <number>
where int(<message_number>) >= 1 and int(<message_number>) <= 7