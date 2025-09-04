<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <user_exchange> <pass_exchange>
<transaction_exchanges> ::= <rset_exchange>

<user_exchange> ::= <Client:USER> <Server:user_response>
<pass_exchange> ::= <Client:PASS> <Server:pass_response>
<rset_exchange> ::= <Client:RSET> <Server:rset_response>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> <username> <crlf>
<PASS> ::= "PASS" <space> <password> <crlf>
<RSET> ::= "RSET" <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <simple_positive_response> | <positive_response> | <negative_response>
<simple_positive_response> ::= '+OK' <crlf>
<pass_response> ::= <positive_response> | <negative_response>
<rset_response> ::= <simple_positive_response> | <positive_response> | <negative_response>
<quit_response> ::= <positive_response> | <negative_response>

<positive_response> ::= "+OK" <space> <text> <crlf>
<negative_response> ::= "-ERR" #$$$$ missing 

# ---- TERMINALS ----
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]*"
<number> ::= r"[0-9]+"

# ---- CONSTRAINTS ----
<username> ::= "debug@localdomain.test"
<password> ::= "NEWpass123"