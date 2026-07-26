# DeepSeek Strict Conservative Budget Implementation

The implementation lives in
`story-os-demo/system/conservative_token_budget.py`.

`ConservativeTokenBudgetPolicy` is frozen and validates every Owner constant,
the exact Provider/model pair, non-exact Layer-A scope, zero retry, no
fallback, unavailable cost, mandatory reconciliation, and consistent ceilings.
Unknown or inconsistent values fail closed.

`evaluate_conservative_request` accepts only the frozen canonical payload. It
requires two or more server-built messages as applicable, explicit non-thinking
mode, JSON Object mode, a JSON instruction, maximum output 512, the registered
counter identity/revision/scope, and a counter that is not marked exact.
Client limits may only reduce server limits. A breach returns a safe code
before Provider work.

The strict formula uses `Decimal("0.25")` and `ROUND_CEILING`; it has no
character fallback. At 2,048 Layer-A text tokens and two messages the result is
3,456 input tokens, leaving the Owner-defined ceilings intact.

The exact readiness implementation remains separate. For a conservative
Profile, `exact_token_counter_available` is always false and it is invalid to
project both exact and conservative availability as true.
