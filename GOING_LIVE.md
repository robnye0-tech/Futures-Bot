# Going live on the $150K Tradeify account — setup guide

Written for the Monday go-live. Read this once end to end before touching
anything, since the pieces depend on each other in order.

## The big picture: how this actually gets from Pine Script to a real order

Nothing in `jarvis_vwap_pullback_mnq.pine` talks to Tradeify/Tradovate
directly - `strategy.entry()`, `strategy.close()`, `strategy.exit()` are all
TradingView's own *simulated* order engine (the same one that's been running
the paper trading test). To place a REAL order, the chain is:

```
Strategy fires a simulated order (entry/exit/stop/target/kill switch/force flat)
        v
TradingView's "Order Fills" alert trigger fires
        v
TradingView Alert (webhook enabled) POSTs a JSON payload to PickMyTrade
        v
PickMyTrade translates that JSON into a real order on your Tradovate account
        v
Fills on the actual $150K Tradeify account
```

Two **separate** alerts are needed on this script, because they serve
different purposes and should NOT be mixed:

1. **Order Fills alert** → routes to PickMyTrade → places real trades.
2. **"Any alert() function call" alert** (the heartbeat, built earlier) →
   routes to your phone/email → just tells you the bot is alive and its
   status. This one should **never** point at PickMyTrade's webhook URL -
   the heartbeat isn't an order and PickMyTrade would have no idea what to
   do with it (best case it's ignored, worst case it errors out the
   connection). Keep these two alerts pointed at different destinations.

## Step 1: Confirm the Tradeify account is ready

- Account purchased and active (150K Lightning Funded, Tradovate platform -
  confirmed from your earlier screenshots: $5,250 EOD trailing drawdown,
  $3,000 daily loss limit, 12 minis/120 micros max contracts).
- Tradeify's bot policy (confirmed from their help docs earlier) requires:
  proof of sole ownership of the strategy, and **a live video of you
  enabling the code on your own PC**. Do this as part of activating
  automation on the account - don't skip it, it's an explicit condition of
  their bot policy, not optional paperwork.
- Confirm you have your Tradovate login credentials for this account handy
  - PickMyTrade will need to connect to it directly.

## Step 2: Set up PickMyTrade

1. Sign up / log into PickMyTrade (paid subscription required for live
   execution - the free tier historically only supports research/testing).
2. In PickMyTrade's dashboard, **connect a broker** → choose Tradovate →
   log in with your Tradeify/Tradovate credentials to link the account.
3. In PickMyTrade, create a new "TradingView Strategy" signal source (their
   terminology may vary slightly by current UI version) mapped to:
   - Symbol: MNQ (make sure it's mapped to the correct MNQ contract month,
     not a stale/expired one - Sept 2026 contract as of this build)
   - The Tradovate account you just connected
4. **Use PickMyTrade's own JSON alert generator** for this mapping - it
   will hand you a message template using TradingView's native strategy
   placeholders (things like `{{strategy.order.action}}`,
   `{{strategy.order.contracts}}`, `{{ticker}}`). Copy this exactly.
   **Do not hand-write this JSON yourself** - PickMyTrade's schema can
   include required fields (webhook secrets, account routing IDs, etc.)
   that aren't obvious from guessing, and getting it wrong risks either a
   silently-ignored alert or a malformed order.
5. Copy the **webhook URL** PickMyTrade gives you for this connection -
   you'll paste this into the TradingView alert in Step 4.

## Step 3: Reconfirm the Pine script's live settings before going further

Open the strategy's Inputs on your live chart and verify (don't just
assume the last paste stuck):

- Base Size = 8, Max Position Size = 8, Scale-In Add Size = 0
- Volume Multiplier = 1.5 (rolling back from the 0.8 experiment)
- ADX Low/High = 15/30, Trend Fast/Slow EMA = 10/50, Breakout Window = 1
- Stop ATR Multiple = 1.5, Target 1/2 ATR Multiple = 1.0/2.0
- Use Fixed-Point Targets = OFF, Enable Fixed-Point Profit Lock = OFF
- Force Flat Hour/Minute = 16/59
- Daily Kill Switch = 1500
- Cumulative Trailing Drawdown Kill Switch = 4000 (still provisional -
  worth a final gut check given it already fired once in testing;
  raise it if you want more room before a halt, lower it if you want
  tighter protection)
- **Reset Cumulative Kill Switch = UNCHECKED** (this one caused a real bug
  when left checked - double check it's off)
- Manual Kill Switch = OFF (this is your on-demand news-event switch -
  leave off unless you're deliberately pausing trading)
- Enable Heartbeat = ON (or your preference)
- Auto-Adjust Parameters By Chart Timeframe = ON, on a 5-minute MNQ1! chart

## Step 4: Create the two TradingView alerts

**Alert 1 - the real trading alert:**
1. Right-click the chart → Add Alert (or the Alert icon in the toolbar).
2. Condition: select the strategy ("Jarvis VWAP Pullback Trend-Continuation
   - MNQ") → choose the **"Order fills"** trigger option (this is specific
   to strategy scripts, distinct from indicator-style conditions) - this
   fires on every single order the strategy places, not just entries.
3. Message: paste PickMyTrade's generated JSON template from Step 2.4.
4. Under Notifications, enable **Webhook URL** and paste PickMyTrade's
   webhook URL from Step 2.5.
5. Frequency: "Once Per Bar Close" (matches the strategy's own
   `calc_on_every_tick = false` / `process_orders_on_close = true` -
   nothing here should ever fire on an unconfirmed intrabar tick).
6. Expiration: set this to never expire (or the longest available window) -
   an expired alert silently stops routing trades with no obvious warning.

**Alert 2 - the heartbeat:**
1. Add Alert again.
2. Condition: the same strategy → **"Any alert() function call"**.
3. Message: leave as default (the script builds its own message dynamically
   via the `alert()` call in the code).
4. Notifications: push notification / email / SMS - whatever reaches your
   phone. **Do NOT set a webhook here pointing at PickMyTrade.**
5. Frequency: "Once Per Bar Close".

## Step 5: Test before trusting it with the funded account

PickMyTrade has a demo/practice routing mode - use it. Let a few real
signals fire through the full pipeline (TradingView -> PickMyTrade ->
demo order) and manually verify:
- Direction (long/short) matches the strategy's signal
- Size matches (8 contracts, or whatever a partial-exit leg calls for)
- It fires on entries, T1/T2 partials, stops, AND force-flat/kill-switch
  closes - not just entries. Every exit type needs to reach the account
  correctly, not just the trade opening.

Only after this checks out cleanly should PickMyTrade's routing be pointed
at the real Tradeify account instead of demo.

## Step 6: Go live

Once Steps 1-5 are all confirmed clean:
1. Switch PickMyTrade's routing from demo to the real Tradeify account.
2. Watch the first few real trades closely rather than walking away
   immediately - confirm fills match what the strategy intended.
3. Keep the paper trading chart or a separate monitoring chart open
   alongside the live one for the first while, so you have an independent
   read on what the strategy *should* be doing to compare against.

## Standing reminders, still true once this is live

- This account still hasn't had a full clean paper trading week the way
  the original plan called for - going live Monday is a deliberate
  acceleration of that plan, not the original one playing out. Worth
  being clear-eyed about that trade-off.
- The Cumulative Kill Switch has already proven it can halt trading for
  an extended stretch (it did exactly that from Aug 19 onward in testing).
  If that happens live, that's the safety system working - the response
  is to review why, not to reflexively clear it and keep going.
- BACKLOG.md still has real open items (a manual sanity ceiling on
  position size, a scheduled news blackout, etc.) that weren't built
  before this go-live - known gaps, not forgotten ones.
