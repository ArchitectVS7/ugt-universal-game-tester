/**
 * SpacerQuest → UGT IPC Bridge (integrations/spacerquest)
 *
 * Subprocess bridge that wraps SpacerQuest's server-side screen router,
 * allowing UGT to control the game via JSON over stdin/stdout.
 *
 * Protocol:
 *   stdin  → {"command": "reset"} | {"command": "step", "action_id": N} | {"command": "close"}
 *   stdout ← {"state": {...}, "terminated": bool, "truncated": bool, "info": {...}}
 *
 * Usage: invoked automatically by UGT's SubprocessAdapter via engine.entry in ugt.config.yaml
 *
 * Key differences from examples/spacerquest/sim_bridge.ts:
 *   - MAX_STEPS_PER_EPISODE = 1000 (long enough for a full game to reach Conqueror rank)
 *   - State includes character.is_conqueror (1 when score >= 10000)
 */

// Intercept stdout so console logs / dotenv banners don't pollute the JSON IPC channel
const originalStdoutWrite = process.stdout.write.bind(process.stdout);
process.stdout.write = (chunk: any, encoding?: any, callback?: any) => {
  const str = chunk.toString();
  const trimmed = str.trim();
  if (
    trimmed.startsWith('{"state":') ||
    trimmed.startsWith('{"terminated":') ||
    trimmed.startsWith('{"error":') ||
    trimmed.startsWith('{"info":')
  ) {
    return originalStdoutWrite(chunk, encoding, callback);
  }
  return process.stderr.write(chunk, encoding, callback);
};

import { createInterface } from 'readline';
import dotenv from 'dotenv';
import { PrismaClient } from '@prisma/client';

dotenv.config({ path: '../../../SpacerQuest/spacerquest-web/.env.ugt' });

import { handleScreenRequest, handleScreenInput } from '../../../SpacerQuest/spacerquest-web/src/sockets/screen-router.js';
import { processDocking } from '../../../SpacerQuest/spacerquest-web/src/game/systems/docking.js';

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const MAX_STEPS_PER_EPISODE = 1000;

// When UGT_VERIFY_MODE=1, start with Commander-rank credits/score so all gated
// features (banking, special equipment, patrol) are reachable in a single run.
const VERIFY_MODE = process.env.UGT_VERIFY_MODE === '1';

const RANK_INDEX: Record<string, number> = {
  LIEUTENANT: 0, COMMANDER: 1, CAPTAIN: 2, COMMODORE: 3, ADMIRAL: 4,
  TOP_DOG: 5, GRAND_MUFTI: 6, MEGA_HERO: 7, GIGA_HERO: 8,
};

// Systems with cheap fuel (Sun-3 8cr/unit, Mira-9 4cr/unit, Vega-6 6cr/unit)
const CHEAP_FUEL_SYSTEMS = [1, 8, 14];

// ---------------------------------------------------------------------------
// Prisma client — connects to the UGT-specific database
// ---------------------------------------------------------------------------
const prisma = new PrismaClient({ log: ['error'] });

// ---------------------------------------------------------------------------
// Bridge State
// ---------------------------------------------------------------------------
let characterId: string | null = null;
let userId: string | null = null;
let currentScreen = 'main-menu';
let stepCount = 0;
let inCombat = false;

// ---------------------------------------------------------------------------
// State Extraction
// ---------------------------------------------------------------------------

async function getGameState(): Promise<Record<string, any>> {
  if (!characterId) return buildEmptyState();

  const character = await prisma.character.findUnique({
    where: { id: characterId },
    include: { ship: true, combatSession: true },
  });

  if (!character || !character.ship) return buildEmptyState();

  const totalCredits = (character.creditsHigh * 10000) + character.creditsLow;
  const bankBalance = (character.bankHigh * 10000) + character.bankLow;
  inCombat = !!(character.combatSession?.active);
  const WIN_SCORE = parseInt(process.env.UGT_WIN_SCORE || '10000', 10);
  const isConqueror = character.score >= WIN_SCORE;

  return {
    character: {
      credits: totalCredits,
      score: character.score,
      rank_index: RANK_INDEX[character.rank] ?? 0,
      current_system: character.currentSystem,
      trip_count: character.tripCount,
      battles_won: character.battlesWon,
      cargo_pods: character.cargoPods,
      destination: character.destination,
      is_lost: character.isLost ? 1 : 0,
      in_combat: inCombat ? 1 : 0,
      bank_balance: bankBalance,
      is_conqueror: isConqueror ? 1 : 0,
      has_patrol_commission: character.hasPatrolCommission ? 1 : 0,
      mission_type: character.missionType,
      trips_completed: character.tripsCompleted,
      number_key: (character as any).numberKey ?? 0,
    },
    ship: {
      fuel: character.ship.fuel,
      hull_strength: character.ship.hullStrength,
      hull_condition: character.ship.hullCondition,
      drive_strength: character.ship.driveStrength,
      drive_condition: character.ship.driveCondition,
      weapon_strength: character.ship.weaponStrength,
      weapon_condition: character.ship.weaponCondition,
      shield_strength: character.ship.shieldStrength,
      shield_condition: character.ship.shieldCondition,
      nav_strength: character.ship.navigationStrength,
      nav_condition: character.ship.navigationCondition,
      life_support_strength: character.ship.lifeSupportStrength,
      life_support_condition: character.ship.lifeSupportCondition,
      robotics_strength: character.ship.roboticsStrength,
      robotics_condition: character.ship.roboticsCondition,
      cabin_strength: character.ship.cabinStrength,
      cabin_condition: character.ship.cabinCondition,
      has_cloaker: character.ship.hasCloaker ? 1 : 0,
      has_auto_repair: character.ship.hasAutoRepair ? 1 : 0,
      has_trans_warp: (character.ship as any).hasTransWarpDrive ? 1 : 0,
      has_titanium_hull: (character.ship as any).hasTitaniumHull ? 1 : 0,
      has_ship_guard: (character.ship as any).hasShipGuard ? 1 : 0,
    },
    turn_number: stepCount,
    victory: isConqueror,
    player_won: isConqueror ? 1 : 0,
    terminated: false,
  };
}

function buildEmptyState(): Record<string, any> {
  return {
    character: {
      credits: 0, score: 0, rank_index: 0, current_system: 1, trip_count: 0,
      battles_won: 0, cargo_pods: 0, destination: 0, is_lost: 0,
      in_combat: 0, bank_balance: 0, is_conqueror: 0,
    },
    ship: {
      fuel: 0, hull_strength: 0, hull_condition: 0, drive_strength: 0,
      weapon_strength: 0, shield_strength: 0, has_cloaker: 0, has_auto_repair: 0,
    },
    turn_number: 0,
    victory: false,
    player_won: 0,
    terminated: true,
  };
}

// ---------------------------------------------------------------------------
// Screen Input Helper
// ---------------------------------------------------------------------------

async function sendInput(input: string): Promise<{ output: string; nextScreen?: string; data?: any }> {
  try {
    const response = await handleScreenInput(characterId!, currentScreen, input);
    if (response.nextScreen) currentScreen = response.nextScreen;
    return response;
  } catch (err: any) {
    return { output: `Error: ${err.message}` };
  }
}

async function goToScreen(screenName: string): Promise<{ output: string; nextScreen?: string }> {
  try {
    currentScreen = screenName;
    const response = await handleScreenRequest(characterId!, screenName);
    if (response.nextScreen) currentScreen = response.nextScreen;
    return response;
  } catch (err: any) {
    return { output: `Error: ${err.message}` };
  }
}

async function ensureMainMenu(): Promise<void> {
  if (currentScreen !== 'main-menu') await goToScreen('main-menu');
}

// ---------------------------------------------------------------------------
// Action Macros (15 actions)
// ---------------------------------------------------------------------------

async function actionWait(): Promise<string> {
  await ensureMainMenu();
  return 'waited';
}

async function actionNavigateCheapFuel(): Promise<string> {
  await ensureMainMenu();
  const state = await getGameState();
  const currentSys = state.character.current_system;

  let bestDest = CHEAP_FUEL_SYSTEMS[0];
  let bestDist = Infinity;
  for (const sys of CHEAP_FUEL_SYSTEMS) {
    if (sys === currentSys) continue;
    const dist = Math.abs(sys - currentSys);
    if (dist < bestDist) { bestDist = dist; bestDest = sys; }
  }

  await sendInput('N');
  const navResp = await sendInput(String(bestDest));
  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }
  await resolveTravel();
  return `navigated_to_${bestDest}`;
}

async function actionNavigateCargoDest(): Promise<string> {
  const state = await getGameState();
  const dest = state.character.destination;
  if (!dest || dest <= 0) return 'no_cargo_dest';

  // Auto end-turn if daily trip limit hit — canTravel() blocks at trip_count >= 2.
  // The game resets trips via a new calendar day; UGT runs on the same day so we reset manually.
  if (state.character.trip_count >= 2) {
    await actionEndTurn();
  }

  // Auto-top-up fuel if below 50 units — silently buys more before navigating so the
  // trip isn't rejected mid-sequence for lack of fuel.
  const freshState = await getGameState();
  if (freshState.ship.fuel < 50 && freshState.character.credits > 500) {
    await actionBuyFuel();
  }

  await ensureMainMenu();
  await sendInput('N');
  const navResp = await sendInput(String(dest));
  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }
  await resolveTravel();
  return `navigated_to_cargo_dest_${dest}`;
}

async function actionNavigateNeighbor(): Promise<string> {
  const state = await getGameState();
  const current = state.character.current_system;
  const dest = current >= 14 ? current - 1 : current + 1;

  await ensureMainMenu();
  await sendInput('N');
  const navResp = await sendInput(String(dest));
  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }
  await resolveTravel();
  return `navigated_to_${dest}`;
}

async function actionBuyFuel(): Promise<string> {
  await ensureMainMenu();
  const preState = await getGameState();
  // Assume max fuel price ~20 cr/unit; buy up to 50 units conservatively
  const maxAffordable = Math.floor(preState.character.credits / 20);
  const unitsToBuy = Math.min(50, Math.max(1, maxAffordable));
  if (maxAffordable < 1) return 'buy_fuel_no_credits';

  // Step 1: main-menu → traders (gate: ship.maxCargoPods >= 1)
  await sendInput('T');
  if (currentScreen !== 'traders') {
    await ensureMainMenu();
    return 'buy_fuel_traders_blocked';
  }

  // Step 2: traders → traders-buy-fuel
  await sendInput('B');
  if (currentScreen !== 'traders-buy-fuel') {
    await ensureMainMenu();
    return 'buy_fuel_screen_failed';
  }

  // Step 3: traders-buy-fuel → enter amount → back to traders
  await sendInput(String(unitsToBuy));
  await ensureMainMenu();
  return 'bought_fuel';
}

async function actionSellFuel(): Promise<string> {
  await ensureMainMenu();

  // Step 1: main-menu → traders (gate: ship.maxCargoPods >= 1)
  await sendInput('T');
  if (currentScreen !== 'traders') {
    await ensureMainMenu();
    return 'sell_fuel_traders_blocked';
  }

  // Step 2: traders → traders-sell-fuel
  await sendInput('S');
  if (currentScreen !== 'traders-sell-fuel') {
    await ensureMainMenu();
    return 'sell_fuel_screen_failed';
  }

  // Step 3: traders-sell-fuel → enter amount
  // Sell only 5 units to stay well above any fuel-floor constraints in the game
  await sendInput('5');
  await ensureMainMenu();
  return 'sold_fuel';
}

async function actionAcceptCargo(): Promise<string> {
  // Guard: if we already have an active cargo contract, deliver it first rather than
  // silently overwriting or wasting a step. This makes the bridge self-correcting when
  // the LLM calls accept_cargo erroneously on an occupied slot.
  const preState = await getGameState();
  if (preState.character.destination > 0) {
    return `already_has_contract_to_dest_${preState.character.destination}_call_navigate_cargo_dest`;
  }

  await ensureMainMenu();

  // Step 1: main-menu → traders (gate: ship.maxCargoPods >= 1)
  await sendInput('T');
  if (currentScreen !== 'traders') {
    await ensureMainMenu();
    return 'accept_cargo_traders_blocked';
  }

  // Step 2: sendInput('A') sets nextScreen='traders-cargo' but does NOT call render().
  // traders-cargo.handleInput checks manifestBoard (set by render) before accepting a
  // selection. Skip sendInput('A') and go directly to goToScreen which calls render(),
  // populating the manifest board before we send the selection key.
  await goToScreen('traders-cargo');
  if (currentScreen !== 'traders-cargo') {
    await ensureMainMenu();
    return 'accept_cargo_no_pods'; // render() returned nextScreen='traders' (gate failed)
  }

  // Step 3: Clear any stale pending confirmation from a prior incomplete accept_cargo call
  await sendInput('N');

  // Step 4: Select first contract (sets pendingManifestChoice)
  await sendInput('1');

  // Step 5: Confirm
  await sendInput('Y');

  await ensureMainMenu();
  return 'accepted_cargo';
}

async function actionDeliverCargo(): Promise<string> {
  return await actionNavigateCargoDest();
}

async function actionUpgradeCheapest(): Promise<string> {
  await ensureMainMenu();
  await sendInput('S');  // main-menu → shipyard
  const resp = await goToScreen('shipyard-upgrade');  // render upgrade screen
  if (resp.output.includes('Select') || resp.output.includes('UPGRADE') || resp.output.includes('component')) {
    // Upgrade HULL ('1') — hull strength controls maxCargoPods, which enables the cargo trading loop.
    // All components cost the same (a * 10000 cr formula), so HULL is always the highest-value upgrade.
    await sendInput('1');
    await ensureMainMenu();
    return 'upgraded_hull';
  }
  await ensureMainMenu();
  return 'upgrade_failed';
}

async function actionRepairShip(): Promise<string> {
  await ensureMainMenu();
  await sendInput('S');
  await sendInput('R');
  await ensureMainMenu();
  return 'repaired';
}

async function actionCombatAttack(): Promise<string> {
  if (!inCombat) return 'not_in_combat';
  const combatResp = await sendInput('A');
  if (combatResp.output.includes('VICTORY') || combatResp.output.includes('destroyed')) {
    inCombat = false;
    await sendInput(' ');
    await ensureMainMenu();
    return 'combat_victory';
  }
  if (combatResp.output.includes('DEFEAT') || combatResp.output.includes('overwhelmed')) {
    inCombat = false;
    await sendInput(' ');
    await ensureMainMenu();
    return 'combat_defeat';
  }
  return 'combat_round';
}

async function actionCombatRetreat(): Promise<string> {
  if (!inCombat) return 'not_in_combat';
  const resp = await sendInput('R');
  if (resp.output.includes('escape') || resp.output.includes('retreat')) {
    inCombat = false;
    await ensureMainMenu();
    return 'retreat_success';
  }
  return 'retreat_failed';
}

async function actionPubGamble(): Promise<string> {
  await ensureMainMenu();
  await sendInput('P');  // → pub
  if (currentScreen !== 'pub') {
    await ensureMainMenu();
    return 'pub_not_accessible';
  }
  // WOF is a 3-step state machine: pick number → pick rolls → pick bet
  await sendInput('W');    // W = Wheel of Fortune (state: pick_number)
  await sendInput('7');    // lucky number 1-60 (state: pick_rolls)
  await sendInput('5');    // 5 rolls, within WOF_MIN_ROLLS/WOF_MAX_ROLLS range (state: pick_bet)
  await sendInput('100');  // bet 100 cr (resolves WOF, clears wofState)
  await ensureMainMenu();
  return 'gambled';
}

async function actionBankDeposit(): Promise<string> {
  await ensureMainMenu();
  const state = await getGameState();
  const credits = state.character.credits;
  if (credits < 100) return 'not_enough_credits';

  await sendInput('B');   // main-menu → bank (Commander+ only)
  if (currentScreen !== 'bank') {
    await ensureMainMenu();
    return 'bank_not_accessible';
  }
  await sendInput('D');   // bank → bank-deposit (returns nextScreen='bank-deposit', output=clear)
  // bank-deposit screen is now active; send amount directly (no prompt text to check).
  const depositAmount = Math.floor(credits / 2);
  await sendInput(String(depositAmount));
  await ensureMainMenu();
  return 'deposited';
}

async function actionEndTurn(): Promise<string> {
  await ensureMainMenu();
  await sendInput('D');
  const resp = await goToScreen('end-turn');
  if (resp.output.includes('End your turn')) {
    await sendInput('Y');
    await sendInput(' ');
  }
  // Reset the daily trip counter so navigation is available next turn.
  // The game's canTravel() only resets via a new calendar day; in UGT sessions all
  // steps run on the same day, so we reset manually here to simulate end-of-day.
  if (characterId) {
    await prisma.character.update({
      where: { id: characterId },
      data: { tripCount: 0, lastTripDate: null },
    });
  }
  await ensureMainMenu();
  return 'ended_turn';
}

// ---------------------------------------------------------------------------
// Extended Actions — individual component upgrades, banking, special equipment,
// patrol, navigation to specific systems, pub, port management, social screens
// ---------------------------------------------------------------------------

async function actionUpgradeComponent(key: string, name: string): Promise<string> {
  await ensureMainMenu();
  await sendInput('S');
  const resp = await goToScreen('shipyard-upgrade');
  if (resp.output.includes('Select') || resp.output.includes('UPGRADE') || resp.output.includes('component') || resp.output.includes('Upgrade')) {
    await sendInput(key);
    await ensureMainMenu();
    return `upgraded_${name}`;
  }
  await ensureMainMenu();
  return 'upgrade_failed';
}

// Game key map (from shipyard-upgrade.ts source):
//   '1'=HULL, '2'=DRIVES, '3'=CABIN, '4'=LIFE_SUPPORT,
//   '5'=WEAPONS, '6'=NAVIGATION, '7'=ROBOTICS, '8'=SHIELDS
async function actionUpgradeDrives(): Promise<string>       { return actionUpgradeComponent('2', 'drives'); }
async function actionUpgradeWeapons(): Promise<string>      { return actionUpgradeComponent('5', 'weapons'); }
async function actionUpgradeShields(): Promise<string>      { return actionUpgradeComponent('8', 'shields'); }
async function actionUpgradeNav(): Promise<string>          { return actionUpgradeComponent('6', 'nav'); }
async function actionUpgradeLifeSupport(): Promise<string>  { return actionUpgradeComponent('4', 'life_support'); }
async function actionUpgradeRobotics(): Promise<string>     { return actionUpgradeComponent('7', 'robotics'); }
async function actionUpgradeCabin(): Promise<string>        { return actionUpgradeComponent('3', 'cabin'); }

async function actionBuySpecialEquipment(key: string, name: string): Promise<string> {
  await ensureMainMenu();
  await sendInput('S');  // → shipyard
  const resp = await sendInput('S');  // → shipyard-special
  if (currentScreen !== 'shipyard-special') {
    await ensureMainMenu();
    return `special_not_accessible_${name}`;
  }
  await sendInput(key);
  const confResp = await sendInput('Y');
  if (confResp.output.includes('cannot') || confResp.output.includes('insufficient') || confResp.output.includes('need')) {
    await ensureMainMenu();
    return `special_buy_blocked_${name}`;
  }
  await ensureMainMenu();
  return `bought_${name}`;
}

async function actionBuyTransWarp(): Promise<string>   { return actionBuySpecialEquipment('6', 'trans_warp'); }
async function actionBuyAutoRepair(): Promise<string>  { return actionBuySpecialEquipment('2', 'auto_repair'); }
async function actionBuyCloaker(): Promise<string>     { return actionBuySpecialEquipment('1', 'cloaker'); }
async function actionBuyStarBuster(): Promise<string>  { return actionBuySpecialEquipment('3', 'star_buster'); }

async function actionBankWithdraw(): Promise<string> {
  await ensureMainMenu();
  await sendInput('B');  // → bank
  if (currentScreen !== 'bank') {
    await ensureMainMenu();
    return 'bank_not_accessible';
  }
  await sendInput('W');    // bank → bank-withdraw (nextScreen='bank-withdraw', output=clear)
  // bank-withdraw is now active; send amount directly
  await sendInput('1000'); // withdraw 1000 credits
  await ensureMainMenu();
  return 'withdrew';
}

async function actionDumpCargo(): Promise<string> {
  await ensureMainMenu();
  await sendInput('T');
  if (currentScreen !== 'traders') {
    await ensureMainMenu();
    return 'traders_blocked';
  }
  await sendInput('D');  // dump cargo
  await ensureMainMenu();
  return 'cargo_dumped';
}

async function actionJoinPatrol(): Promise<string> {
  await ensureMainMenu();
  await sendInput('R');  // → registry
  if (currentScreen !== 'registry') {
    await ensureMainMenu();
    return 'registry_not_accessible';
  }
  await sendInput('S');  // → space-patrol HQ
  if (currentScreen !== 'space-patrol') {
    await ensureMainMenu();
    return 'patrol_not_accessible';
  }
  await sendInput('J');  // join/take oath
  await sendInput('Y');  // confirm oath
  await ensureMainMenu();
  return 'joined_patrol';
}

async function actionNavigateToSystem(destSystem: number): Promise<string> {
  const state = await getGameState();
  if (state.character.current_system === destSystem) return `already_at_system_${destSystem}`;
  if (state.character.trip_count >= 2) await actionEndTurn();
  const freshState = await getGameState();
  if (freshState.ship.fuel < 30 && freshState.character.credits > 300) await actionBuyFuel();
  await ensureMainMenu();
  await sendInput('N');
  const navResp = await sendInput(String(destSystem));
  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }
  await resolveTravel();
  return `navigated_to_system_${destSystem}`;
}

async function actionNavigateToSun3(): Promise<string>    { return actionNavigateToSystem(1); }
async function actionNavigateToPolaris(): Promise<string> { return actionNavigateToSystem(17); }
async function actionNavigateToMizar(): Promise<string>   { return actionNavigateToSystem(18); }

async function actionVisitWiseOne(): Promise<string> {
  const state = await getGameState();
  if (state.character.current_system !== 17) await actionNavigateToSystem(17);
  // wise-one.render() is what generates + persists numberKey — must use goToScreen (not sendInput)
  // so that the render function is called, not just a screen transition.
  await goToScreen('wise-one');  // calls render → generateNumberKey() → prisma.character.update
  await sendInput(' ');           // any key → nextScreen: rim-port
  await ensureMainMenu();
  return 'visited_wise_one';
}

async function actionVisitSage(): Promise<string> {
  const state = await getGameState();
  if (state.character.current_system !== 18) await actionNavigateToSystem(18);
  await ensureMainMenu();
  await sendInput('A');  // sage key, system 18 only
  await sendInput('A');  // answer 'A' (one of 16 choices)
  await sendInput(' ');  // continue
  await ensureMainMenu();
  return 'visited_sage';
}

async function actionReadSpaceNews(): Promise<string> {
  await ensureMainMenu();
  await sendInput('J');  // space news
  await sendInput('S');  // show all
  await sendInput('Q');  // quit
  await ensureMainMenu();
  return 'read_news';
}

async function actionViewStats(): Promise<string> {
  await ensureMainMenu();
  await sendInput('X');  // ship stats screen
  await sendInput('Q');  // or any key to return
  await ensureMainMenu();
  return 'viewed_stats';
}

async function actionBuyDrink(): Promise<string> {
  await ensureMainMenu();
  await sendInput('P');  // → pub
  if (currentScreen !== 'pub') {
    await ensureMainMenu();
    return 'pub_not_accessible';
  }
  await sendInput('B');  // buy drink (50 cr)
  await ensureMainMenu();
  return 'bought_drink';
}

async function actionViewRegistry(): Promise<string> {
  await ensureMainMenu();
  await sendInput('R');  // → registry
  if (currentScreen !== 'registry') {
    await ensureMainMenu();
    return 'registry_blocked';
  }
  await sendInput('L');  // → library
  await sendInput('Q');  // quit
  await ensureMainMenu();
  return 'viewed_registry';
}

async function actionBuyPort(): Promise<string> {
  const state = await getGameState();
  if (state.character.credits < 100000) return 'not_enough_credits_for_port';
  await ensureMainMenu();
  await sendInput('F');  // → port accounts
  if (currentScreen !== 'port-accounts') {
    await ensureMainMenu();
    return 'port_accounts_not_accessible';
  }
  await sendInput('B');  // buy port
  // Port buy accepts systems 1-14 only; use system 1 (Sun-3) which is always available.
  // We cannot use current_system because reach_system_17/18 may have left us at a rim system.
  await sendInput('1');   // system 1 (Sun-3) — always in valid range
  await sendInput('Y');   // first confirm (buy-sys-ok → buy-price-ok)
  await sendInput('Y');   // second confirm (buy-price-ok → purchase)
  await ensureMainMenu();
  return 'bought_port';
}

async function actionSellPort(): Promise<string> {
  // Look up owned port system from DB rather than using current_system
  // (character may have navigated away from the port between buy and sell)
  if (!characterId) return 'no_character';
  const port = await prisma.portOwnership.findFirst({ where: { characterId } });
  if (!port) return 'no_port_owned';

  await ensureMainMenu();
  await sendInput('F');  // → port-accounts
  if (currentScreen !== 'port-accounts') {
    await ensureMainMenu();
    return 'port_accounts_not_accessible';
  }
  await sendInput('S');                     // null → sell-prompt: "[Cr:...][Realty Market]: (S)ell [Q]uit:"
  await sendInput('S');                     // sell-prompt → sell-system: "Choice: (1-14)"
  await sendInput(String(port.systemId));   // sell-system → sell-sys-ok: confirm system
  await sendInput('Y');                     // sell-sys-ok → sell-price-ok: confirm sell
  await sendInput('Y');                     // sell-price-ok → done: price confirmed
  await ensureMainMenu();
  return 'sold_port';
}

// ---------------------------------------------------------------------------
// Travel Resolution
// ---------------------------------------------------------------------------

async function resolveTravel(): Promise<void> {
  if (!characterId) return;

  const travelState = await prisma.travelState.findUnique({ where: { characterId } });

  if (travelState && travelState.inTransit) {
    await prisma.travelState.update({
      where: { characterId },
      data: { inTransit: false },
    });

    // startTravel() already increments tripCount (daily limit counter) and sets lastTripDate.
    // We only set the destination and update the distance traveled here.
    await prisma.character.update({
      where: { id: characterId },
      data: {
        currentSystem: travelState.destinationSystem,
        astrecsTraveled: {
          increment: Math.abs(travelState.destinationSystem - travelState.originSystem),
        },
      },
    });

    // Run SpacerQuest's arrival handler: processes cargo delivery, score bonuses,
    // and any other arrival events (pirate encounters, Andromeda, etc.)
    await processDocking(characterId, travelState.destinationSystem);

    currentScreen = 'main-menu';
  }
}

// ---------------------------------------------------------------------------
// Action Dispatch
// ---------------------------------------------------------------------------

const ACTION_MAP: Record<number, () => Promise<string>> = {
  // Core loop (IDs 0-14, unchanged for RL compatibility)
  0: actionWait,
  1: actionNavigateCheapFuel,
  2: actionNavigateCargoDest,
  3: actionNavigateNeighbor,
  4: actionBuyFuel,
  5: actionSellFuel,
  6: actionAcceptCargo,
  7: actionDeliverCargo,
  8: actionUpgradeCheapest,
  9: actionRepairShip,
  10: actionCombatAttack,
  11: actionCombatRetreat,
  12: actionPubGamble,
  13: actionBankDeposit,
  14: actionEndTurn,
  // Phase 1 extended actions (IDs 15+)
  15: actionUpgradeDrives,
  16: actionUpgradeWeapons,
  17: actionUpgradeShields,
  18: actionUpgradeNav,
  19: actionUpgradeLifeSupport,
  20: actionUpgradeRobotics,
  21: actionUpgradeCabin,
  22: actionBankWithdraw,
  23: actionBuyTransWarp,
  24: actionBuyAutoRepair,
  25: actionBuyCloaker,
  26: actionBuyStarBuster,
  27: actionDumpCargo,
  28: actionJoinPatrol,
  29: actionNavigateToSun3,
  30: actionNavigateToPolaris,
  31: actionNavigateToMizar,
  32: actionVisitWiseOne,
  33: actionVisitSage,
  34: actionReadSpaceNews,
  35: actionViewStats,
  36: actionBuyDrink,
  37: actionViewRegistry,
  38: actionBuyPort,
  39: actionSellPort,
};

// ---------------------------------------------------------------------------
// Reset: Create or reset a test character
// ---------------------------------------------------------------------------

// Per-process email prevents parallel bridge instances from deleting each other's characters.
const PROCESS_EMAIL = `ugt-${process.pid}@spacerquest.test`;

async function resetGame(): Promise<Record<string, any>> {
  stepCount = 0;
  inCombat = false;
  currentScreen = 'main-menu';

  let user = await prisma.user.findFirst({ where: { email: PROCESS_EMAIL } });

  if (!user) {
    user = await prisma.user.create({
      data: {
        bbsUserId: `ugt-${process.pid}`,
        email: PROCESS_EMAIL,
        displayName: 'UGT Agent',
      },
    });
  }
  userId = user.id;

  // Always clear all port ownerships so any system is available for purchase during verification.
  // Must run unconditionally (not inside if-existingChar) in case other game users own ports.
  await prisma.portOwnership.deleteMany({});

  const existingChar = await prisma.character.findFirst({ where: { userId } });
  if (existingChar) {
    await prisma.$transaction([
      prisma.combatSession.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.battleRecord.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.travelState.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.gameLog.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.allianceMembership.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.ship.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.character.delete({ where: { id: existingChar.id } }),
    ]);
  }

  // VERIFY_MODE: start at Commander rank with 500k credits so all gated features
  // (banking, special equipment, patrol, port purchase) are reachable without
  // needing 75+ cargo deliveries to accumulate rank/credits organically.
  const character = await prisma.character.create({
    data: {
      userId,
      name: 'UGT-Agent',
      shipName: 'Neural-Net-1',
      currentSystem: 1,
      creditsHigh: VERIFY_MODE ? 50 : 1,   // 50*10000=500,000 or 1*10000+5000=15,000
      creditsLow: VERIFY_MODE ? 0 : 5000,
      rank: VERIFY_MODE ? 'COMMANDER' : 'LIEUTENANT',
      score: VERIFY_MODE ? 200 : 0,        // Commander threshold = 150
      missionType: 0,
      cargoPods: 0,
      destination: 0,
    },
  });

  characterId = character.id;

  await prisma.ship.create({
    data: {
      characterId: character.id,
      hullStrength: 5,      hullCondition: 9,
      driveStrength: 5,     driveCondition: 9,
      cabinStrength: 1,     cabinCondition: 9,
      lifeSupportStrength: 5, lifeSupportCondition: 9,
      weaponStrength: 1,    weaponCondition: 9,
      // precision = floor(navStrength*navCondition/10). Must be > 40 to guarantee on-course.
      // 99*9=891 → precision=89 → always on course regardless of RNG roll.
      navigationStrength: 99, navigationCondition: 9,
      roboticsStrength: 1,  roboticsCondition: 9,
      shieldStrength: 1,    shieldCondition: 9,
      fuel: VERIFY_MODE ? 200 : 50,
      cargoPods: 0,
      // calculateMaxCargoPods(hullStrength=5, hullCondition=9, titanium=false) = (9+1)*5 = 50
      // The cargo screen uses floor(maxCargoPods/2) pods per contract, so floor(1/2)=0 with
      // maxCargoPods=1 — contracts would carry 0 pods and delivery would silently fail.
      maxCargoPods: 50,
    },
  });

  const state = await getGameState();
  return {
    state,
    terminated: false,
    truncated: false,
    info: { action: 'reset', character_id: characterId },
  };
}

// ---------------------------------------------------------------------------
// Step: Execute one action
// ---------------------------------------------------------------------------

async function stepGame(actionId: number): Promise<Record<string, any>> {
  stepCount++;

  const actionFn = ACTION_MAP[actionId] ?? actionWait;
  let actionResult: string;

  try {
    actionResult = await actionFn();
  } catch (err: any) {
    actionResult = `error: ${err.message}`;
  }

  const state = await getGameState();

  const WIN_SCORE = parseInt(process.env.UGT_WIN_SCORE || '10000', 10);
  const isConqueror = state.character.score >= WIN_SCORE;
  const isDead = state.ship.hull_condition <= 0 && state.character.credits <= 0;
  const isStepLimit = stepCount >= MAX_STEPS_PER_EPISODE;
  const terminated = isConqueror || isDead;
  const truncated = isStepLimit && !terminated;

  return {
    state: { ...state, victory: isConqueror, player_won: isConqueror ? 1 : 0 },
    terminated: terminated || truncated,
    truncated,
    info: {
      action_id: actionId,
      action_result: actionResult,
      step: stepCount,
      screen: currentScreen,
      won: isConqueror,
    },
  };
}

// ---------------------------------------------------------------------------
// Main IPC Loop
// ---------------------------------------------------------------------------

async function main() {
  const rl = createInterface({ input: process.stdin });

  for await (const line of rl) {
    if (!line.trim()) continue;

    let cmd: any;
    try {
      cmd = JSON.parse(line.trim());
    } catch {
      continue;
    }

    const command = cmd.command;
    let response: Record<string, any>;

    if (command === 'reset') {
      response = await resetGame();
    } else if (command === 'step') {
      response = await stepGame(cmd.action_id ?? 0);
    } else if (command === 'close') {
      await prisma.$disconnect();
      process.exit(0);
    } else {
      response = { error: `Unknown command: ${command}` };
    }

    process.stdout.write(JSON.stringify(response) + '\n');
  }
}

main().catch((err) => {
  process.stderr.write(`Bridge fatal error: ${err.message}\n`);
  process.exit(1);
});
