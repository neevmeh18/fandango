<start> ::= <banner_exchange> <authorization_state>

<banner_exchange> ::= <Server:banner>
<banner> ::= <text> <crlf>

# ---- STATE DEFINITIONS ----
<authorization_state> ::= <auth_exchanges> <transaction_state>
<transaction_state> ::= <transaction_exchanges> <end_state>
<end_state> ::= <quit_exchange>

# ---- EXCHANGES ----
<auth_exchanges> ::= <Client:USER> <Server:user_response> <Client:PASS> <Server:pass_response>
<transaction_exchanges> ::= <Client:UIDL> <Server:uidl_response>
<quit_exchange> ::= <Client:QUIT> <Server:quit_response>

# ---- CLIENT COMMANDS ----
<USER> ::= "USER" <space> <username> <crlf>
<PASS> ::= "PASS" <space> <password> <crlf>
<UIDL> ::= "UIDL" <crlf>
<QUIT> ::= "QUIT" <crlf>

# ---- SERVER RESPONSES ----
<user_response> ::= <positive_response> | <bare_positive_response> | <negative_response>
<bare_positive_response> ::= '+OK' <crlf>
<pass_response> ::= <positive_response> | <negative_response>
<uidl_response> ::= <positive_response> <uidl_listing> | <negative_response> |  <bare_positive_response> <uidl_listing>
<quit_response> ::= <positive_response> | <negative_response>

<positive_response> ::= "+OK" <space> <text> <crlf>
<negative_response> ::= "-ERR" <space> <text> <crlf>

<uidl_listing> ::= (<message_number> <space> <unique_id> <crlf>)* <termination>
<termination> ::= "." <crlf> 

# ---- TERMINALS ----
<username> ::= "debug@localdomain.test"
<password> ::= "NEWpass123"
<unique_id> ::= r"[^\r\n]+"
<message_number> ::= <number>
<number> ::= r"[0-9]+"
<space> ::= " "
<crlf> ::= "\r\n"
<text> ::= r"[^\r\n]+"

# ---- CONSTRAINTS ----
<message_number> ::= <number>
where int(<message_number>) >= 0 and int(<message_number>) <= 5