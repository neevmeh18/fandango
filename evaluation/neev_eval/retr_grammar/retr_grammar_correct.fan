<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <authorization_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<authorization_exchanges> ::= <user_exchange> <pass_exchange>
<transaction_exchanges> ::= <retr_exchange>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

<user_exchange> ::= <Client:USER> <Server:user_response>
<pass_exchange> ::= <Client:PASS> <Server:pass_response>
<retr_exchange> ::= <Client:RETR> <Server:retr_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> <username> <crlf>
<PASS> ::= "PASS" <space> <password> <crlf>
<RETR> ::= "RETR" <space> <message_number> <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response> | <negative_response>
<positive_response> ::= '+OK' <crlf> | '+OK' <space> <text> <crlf>
<negative_response> ::= "-ERR" <space> <text> <crlf>
<pass_response> ::= <positive_response> | <negative_response>
<retr_response> ::= <positive_response> <message_content>+ <multiline_termination> | <negative_response>
<quit_response> ::= <positive_response> | <negative_response>

# ---- TERMINALS ----
<username> ::= "debug@localdomain.test"
<password> ::= "NEWpass123"
<message_number> ::= <number>
where int(<message_number>) >= 1 and int(<message_number>) <= 7

<message_content> ::= <text> <crlf>| <crlf>
<multiline_termination> ::= "." <crlf>

<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"
