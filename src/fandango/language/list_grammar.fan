<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <user_exchange> <pass_exchange>
<transaction_exchanges> ::= <list_exchange>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

<user_exchange> ::= <Client:USER> <Server:user_response>
<pass_exchange> ::= <Client:PASS> <Server:pass_response>
<list_exchange> ::= <Client:LIST> <Server:list_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> "debug@localdomain.test" <crlf>
<PASS> ::= "PASS" <space> "NEWpass123" <crlf>
<LIST> ::= "LIST" <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response>
<positive_response> ::= '+OK' <crlf>
<pass_response> ::= <positive_response> | <negative_response>
<list_response> ::= <positive_response_multiline> | <negative_response>
<quit_response> ::= <positive_response> | <negative_response>

<positive_response_multiline> ::= "+OK" <space> <text> <crlf> <multiline_data>
<negative_response> ::= "-ERR" <space> <text> <crlf>
<multiline_data> ::= (<text> <crlf>)* "."

# ---- TERMINALS ----
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"
