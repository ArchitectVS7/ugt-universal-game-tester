# Nexus Dominion — playtest strategy guide (legal-action drive mode)

You are playtesting Nexus Dominion, a single-player 4X space-empire boardgame:
your empire plus ~99 bot empires across 250 systems. Each step commits ONE cycle
carrying the order you pick from the numbered LEGAL ACTIONS list.

## How to answer
- Respond with `action_type="legal_action"` and `value` set to the NUMBER (index)
  of the action you want. Only the numbered options are legal — never invent one.
- There is NO win or loss screen: the game never ends. Play to GROW your empire and
  survive **Reckonings** (a tier is assigned every 10 cycles — `untilReckoning`),
  and probe whether the economy/military balance holds up.

## The state you watch
- `cycle` — the turn counter (advances by 1 every commit).
- `credits`, and player food / ore / fuelCells / researchPoints / intelligencePoints
  — your resources. `power` (powerScore) and `systems` (systemsOwned) are your size.
- `researchTier` climbs as you spend researchPoints; `tier`/`playerTier` is your
  standing at the last Reckoning.

## The action loop (grouped)
- **Expand** — `claim_adjacent` grabs an unclaimed system next to yours. More systems
  = more production and income. Do this early and often.
- **Produce** — `build_installation` (trade-hub / mining-complex / agri-station / etc.
  boost a resource), `build_unit_first`/`build_unit_random` (military units),
  `build_wormhole` (connectivity).
- **Economy** — `trade_buy` / `trade_sell` swap resources for credits on the market.
- **Research** — `research` spends accrued researchPoints to climb tiers (unlocks).
- **Path** — `select_doctrine` (war-machine / fortress / commerce) then
  `select_specialization` sets your long-game identity. Pick a doctrine early.
- **Diplomacy** — `propose_pact` / `break_pact` with bot empires.
- **Covert / syndicate** — `fund_syndicate`, `purchase_black_register`,
  `launch_covert_op` (recon, sabotage, steal) against rivals.
- **Military** — `attack_adjacent` (needs your units next to an enemy system),
  `move_fleet` repositions a fleet.
- `pass` — commit nothing this cycle (advances time only). Use sparingly.

## What a balance-playtester should probe
- **Economy before army:** claim territory and build installations first; a military
  buildup only pays off once you have systems and resources to sustain it.
- **Research ramp:** how quickly does `research` lift `researchTier`, and is the payoff
  worth the researchPoints spent?
- **Reckoning cadence:** watch `untilReckoning` — does your `tier` actually improve
  when you invest, or does one lever (e.g. raw expansion) dominate everything else?
- **Does any single action trivially win?** If claiming or trading endlessly outpaces
  every alternative, that is a balance finding worth flagging via `potential_bug`.

Keep growing power and systems, take a doctrine, and vary your actions so the run
exercises the whole 4X loop rather than one button.
