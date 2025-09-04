<start> ::= <banner_exchange> <authorization_state>
<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <Client:USER> <Server:user_response> <Client:PASS> <Server:pass_response>
<transaction_exchanges> ::= <Client:LIST> <Server:list_response>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> "debug@localdomain.test" <crlf>
<PASS> ::= "PASS" <space> "NEWpass123" <crlf>
<LIST> ::= "LIST" <crlf> | "LIST" <space> <number> <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response_alone> | <negative_response>
<pass_response> ::= <positive_response> | <negative_response>
<list_response> ::= <positive_response> <multi_line> | <negative_response> #$$$$$$$$$$$$$$$$$$$$$missing alts here
<quit_response> ::= <positive_response> | <negative_response>
<positive_response_alone> ::= '+OK' <crlf>
<positive_response> ::= "+OK" <space> <text> <crlf>
<negative_response> ::= "-ERR" <space> <text> <crlf>
<multi_line> ::= (<text> <crlf>)* <termination>
<termination> ::= "." <crlf>

# ---- TERMINALS ----
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"
