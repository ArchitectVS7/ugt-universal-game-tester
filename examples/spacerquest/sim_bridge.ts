/**
 * SpacerQuest → UGT IPC Bridge
 *
 * A TypeScript subprocess bridge that wraps SpacerQuest's server-side screen
 * router, allowing UGT to control the game via the standard subprocess adapter
 * protocol (JSON over stdin/stdout).
 *
 * Protocol:
 *   stdin  → {"command": "reset"} or {"command": "step", "action_id": N} or {"command": "close"}
 *   stdout ← {"state": {...}, "terminated": bool, "truncated": bool, "info": {...}}
 *
 * Usage:
 *   Invoked automatically by UGT's SubprocessAdapter. Not intended for direct use.
 *   The ugt.config.yaml engine.entry field points to this file via: node --import tsx sim_bridge.ts
 */

// Intercept stdout to prevent console logs or dotenv banners from polluting the JSON IPC protocol
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

// Load isolated UGT environment variables
dotenv.config({ path: '../../../SpacerQuest/spacerquest-web/.env.ugt' });

import { handleScreenRequest, handleScreenInput } from '../../../SpacerQuest/spacerquest-web/src/sockets/screen-router.js';


// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const MAX_STEPS_PER_EPISODE = 50;

const RANK_INDEX: Record<string, number> = {
  LIEUTENANT: 0, COMMANDER: 1, CAPTAIN: 2, COMMODORE: 3, ADMIRAL: 4,
  TOP_DOG: 5, GRAND_MUFTI: 6, MEGA_HERO: 7, GIGA_HERO: 8,
};

// Systems with cheap fuel (for the navigate_cheap_fuel action)
const CHEAP_FUEL_SYSTEMS = [1, 8, 14]; // Sun-3 (8cr), Mira-9 (4cr), Vega-6 (6cr)

// ---------------------------------------------------------------------------
// Prisma client — connects to the UGT-specific database
// ---------------------------------------------------------------------------
const prisma = new PrismaClient({
  log: ['error'],
});

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
  if (!characterId) {
    return buildEmptyState();
  }

  const character = await prisma.character.findUnique({
    where: { id: characterId },
    include: { ship: true, combatSession: true },
  });

  if (!character || !character.ship) {
    return buildEmptyState();
  }

  const totalCredits = (character.creditsHigh * 10000) + character.creditsLow;
  const bankBalance = (character.bankHigh * 10000) + character.bankLow;
  inCombat = !!(character.combatSession?.active);

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
    },
    ship: {
      fuel: character.ship.fuel,
      hull_strength: character.ship.hullStrength,
      hull_condition: character.ship.hullCondition,
      drive_strength: character.ship.driveStrength,
      weapon_strength: character.ship.weaponStrength,
      shield_strength: character.ship.shieldStrength,
      has_cloaker: character.ship.hasCloaker ? 1 : 0,
      has_auto_repair: character.ship.hasAutoRepair ? 1 : 0,
    },
    turn_number: stepCount,
    // Victory/lifecycle flags
    victory: character.score >= 10000,
    player_won: character.score >= 10000 ? 1 : 0,
    terminated: false, // caller overrides this
  };
}

function buildEmptyState(): Record<string, any> {
  return {
    character: {
      credits: 0, score: 0, rank_index: 0, current_system: 1, trip_count: 0,
      battles_won: 0, cargo_pods: 0, destination: 0, is_lost: 0,
      in_combat: 0, bank_balance: 0,
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

/**
 * Send an input to the current screen and process the response.
 * Updates currentScreen based on the response's nextScreen field.
 * Returns the ScreenResponse for inspection.
 */
async function sendInput(input: string): Promise<{ output: string; nextScreen?: string; data?: any }> {
  try {
    const response = await handleScreenInput(characterId!, currentScreen, input);
    if (response.nextScreen) {
      currentScreen = response.nextScreen;
    }
    return response;
  } catch (err: any) {
    return { output: `Error: ${err.message}` };
  }
}

/**
 * Navigate to a specific screen and render it.
 */
async function goToScreen(screenName: string): Promise<{ output: string; nextScreen?: string }> {
  try {
    currentScreen = screenName;
    const response = await handleScreenRequest(characterId!, screenName);
    if (response.nextScreen) {
      currentScreen = response.nextScreen;
    }
    return response;
  } catch (err: any) {
    return { output: `Error: ${err.message}` };
  }
}

/**
 * Ensure we're back at the main menu before executing the next action.
 */
async function ensureMainMenu(): Promise<void> {
  if (currentScreen !== 'main-menu') {
    await goToScreen('main-menu');
  }
}

// ---------------------------------------------------------------------------
// Action Macros (15 actions)
// ---------------------------------------------------------------------------

/** Action 0: Wait / no-op. Just re-render main menu. */
async function actionWait(): Promise<string> {
  await ensureMainMenu();
  return 'waited';
}

/** Action 1: Navigate to nearest cheap fuel system. */
async function actionNavigateCheapFuel(): Promise<string> {
  await ensureMainMenu();
  const state = await getGameState();
  const currentSys = state.character.current_system;

  // Find the nearest cheap fuel system we're not already at
  let bestDest = CHEAP_FUEL_SYSTEMS[0];
  let bestDist = Infinity;
  for (const sys of CHEAP_FUEL_SYSTEMS) {
    if (sys === currentSys) continue;
    const dist = Math.abs(sys - currentSys);
    if (dist < bestDist) {
      bestDist = dist;
      bestDest = sys;
    }
  }

  // Navigate: N → destination → Y (accept fee)
  await sendInput('N');
  const navResp = await sendInput(String(bestDest));

  // Check if we got a fee confirmation prompt
  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }

  // Wait for travel to complete by resolving it server-side
  await resolveTravel();

  return `navigated_to_${bestDest}`;
}

/** Action 2: Navigate to cargo destination. */
async function actionNavigateCargoDest(): Promise<string> {
  const state = await getGameState();
  const dest = state.character.destination;
  if (!dest || dest <= 0) return 'no_cargo_dest';

  await ensureMainMenu();
  await sendInput('N');
  const navResp = await sendInput(String(dest));

  if (navResp.output.includes('pay the fee') || navResp.output.includes('Launch now')) {
    await sendInput('Y');
  }

  await resolveTravel();
  return `navigated_to_cargo_dest_${dest}`;
}

/** Action 3: Navigate to an adjacent system. */
async function actionNavigateNeighbor(): Promise<string> {
  const state = await getGameState();
  const current = state.character.current_system;

  // Simple heuristic: go +1 or -1, staying in range 1-14 for core systems
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

/** Action 4: Buy fuel (max affordable amount). */
async function actionBuyFuel(): Promise<string> {
  await ensureMainMenu();
  await sendInput('T'); // Traders
  const resp = await sendInput('B'); // Buy fuel

  if (resp.output.includes('units to buy') || resp.output.includes('BUY')) {
    // Buy a reasonable amount — 200 units
    await sendInput('200');
    await ensureMainMenu();
    return 'bought_fuel';
  }

  await ensureMainMenu();
  return 'buy_fuel_failed';
}

/** Action 5: Sell fuel. */
async function actionSellFuel(): Promise<string> {
  await ensureMainMenu();
  await sendInput('T'); // Traders
  await sendInput('S'); // Sell fuel
  await sendInput('50'); // Sell 50 units
  await ensureMainMenu();
  return 'sold_fuel';
}

/** Action 6: Accept cargo contract. */
async function actionAcceptCargo(): Promise<string> {
  await ensureMainMenu();
  await sendInput('T'); // Traders
  const resp = await sendInput('A'); // Accept cargo

  if (resp.output.includes('Accept') || resp.output.includes('CONTRACT')) {
    await sendInput('Y');
    await ensureMainMenu();
    return 'accepted_cargo';
  }

  await ensureMainMenu();
  return 'accept_cargo_failed';
}

/** Action 7: Deliver cargo (navigate to destination). */
async function actionDeliverCargo(): Promise<string> {
  // This is effectively the same as navigate_cargo_dest
  return await actionNavigateCargoDest();
}

/** Action 8: Upgrade cheapest affordable component. */
async function actionUpgradeCheapest(): Promise<string> {
  await ensureMainMenu();
  await sendInput('S'); // Shipyard

  const resp = await sendInput('U'); // Upgrade
  if (resp.output.includes('Select') || resp.output.includes('UPGRADE') || resp.output.includes('component')) {
    // Upgrade robotics (cheapest at 4,000 cr) = component 8
    await sendInput('8');
    await ensureMainMenu();
    return 'upgraded_robotics';
  }

  await ensureMainMenu();
  return 'upgrade_failed';
}

/** Action 9: Repair all ship components. */
async function actionRepairShip(): Promise<string> {
  await ensureMainMenu();
  await sendInput('S'); // Shipyard
  await sendInput('R'); // Repair
  await ensureMainMenu();
  return 'repaired';
}

/** Action 10: Attack in combat. */
async function actionCombatAttack(): Promise<string> {
  if (!inCombat) return 'not_in_combat';

  const combatResp = await sendInput('A'); // Attack
  if (combatResp.output.includes('VICTORY') || combatResp.output.includes('destroyed')) {
    inCombat = false;
    await sendInput(' '); // Press any key
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

/** Action 11: Retreat from combat. */
async function actionCombatRetreat(): Promise<string> {
  if (!inCombat) return 'not_in_combat';

  const resp = await sendInput('R'); // Retreat
  if (resp.output.includes('escape') || resp.output.includes('retreat')) {
    inCombat = false;
    await ensureMainMenu();
    return 'retreat_success';
  }
  return 'retreat_failed';
}

/** Action 12: Play Wheel of Fortune. */
async function actionPubGamble(): Promise<string> {
  await ensureMainMenu();
  await sendInput('P'); // Pub
  await sendInput('G'); // Gamble
  await sendInput('1'); // Wheel of Fortune

  // Pick number 7, 5 rolls, bet 100
  await sendInput('7');
  await sendInput('5');
  await sendInput('100');

  await ensureMainMenu();
  return 'gambled';
}

/** Action 13: Bank deposit (half of hand credits). */
async function actionBankDeposit(): Promise<string> {
  await ensureMainMenu();
  const state = await getGameState();
  const credits = state.character.credits;

  if (credits < 100) return 'not_enough_credits';

  await sendInput('B'); // Bank
  const bankResp = await sendInput('D'); // Deposit

  if (bankResp.output.includes('amount') || bankResp.output.includes('DEPOSIT') || bankResp.output.includes('deposit')) {
    const depositAmount = Math.floor(credits / 2);
    await sendInput(String(depositAmount));
  }

  await ensureMainMenu();
  return 'deposited';
}

/** Action 14: End turn (bots take their turns). */
async function actionEndTurn(): Promise<string> {
  await ensureMainMenu();
  await sendInput('D'); // Done

  const resp = await goToScreen('end-turn');
  if (resp.output.includes('End your turn')) {
    await sendInput('Y');
    // Wait briefly for bot turns
    await sendInput(' '); // Any key to continue
  }

  await ensureMainMenu();
  return 'ended_turn';
}

// ---------------------------------------------------------------------------
// Travel Resolution
// ---------------------------------------------------------------------------

/**
 * Resolve any in-progress travel immediately by updating the database.
 * In the real game, travel takes real-time seconds. For the UGT bridge,
 * we fast-forward by directly completing the travel state.
 */
async function resolveTravel(): Promise<void> {
  if (!characterId) return;

  const travelState = await prisma.travelState.findUnique({
    where: { characterId },
  });

  if (travelState && travelState.inTransit) {
    // Complete travel instantly
    await prisma.travelState.update({
      where: { characterId },
      data: { inTransit: false },
    });

    // Move character to destination
    await prisma.character.update({
      where: { id: characterId },
      data: {
        currentSystem: travelState.destinationSystem,
        tripCount: { increment: 1 },
        tripsCompleted: { increment: 1 },
        astrecsTraveled: {
          increment: Math.abs(travelState.destinationSystem - travelState.originSystem),
        },
      },
    });

    currentScreen = 'main-menu';

    // TODO: seeded PRNG encounter roll (use mulberry32 when implementing)
    // if (seededRandom() < 0.3) { /* resolve combat encounter */ }
  }
}

// ---------------------------------------------------------------------------
// Action Dispatch
// ---------------------------------------------------------------------------

const ACTION_MAP: Record<number, () => Promise<string>> = {
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
};

// ---------------------------------------------------------------------------
// Reset: Create or reset a test character
// ---------------------------------------------------------------------------

async function resetGame(): Promise<Record<string, any>> {
  stepCount = 0;
  inCombat = false;
  currentScreen = 'main-menu';

  // Find or create the UGT test user
  let user = await prisma.user.findFirst({
    where: { email: 'ugt@spacerquest.test' },
  });

  if (!user) {
    user = await prisma.user.create({
      data: {
        bbsUserId: 'ugt-test-user',
        email: 'ugt@spacerquest.test',
        displayName: 'UGT Agent',
      },
    });
    userId = user.id;
  } else {
    userId = user.id;
  }

  // Delete existing character and ship for clean reset
  const existingChar = await prisma.character.findFirst({
    where: { userId: userId },
  });

  if (existingChar) {
    // Clean up related records
    await prisma.$transaction([
      prisma.combatSession.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.battleRecord.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.travelState.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.gameLog.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.portOwnership.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.allianceMembership.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.ship.deleteMany({ where: { characterId: existingChar.id } }),
      prisma.character.delete({ where: { id: existingChar.id } }),
    ]);
  }

  // Create fresh character with original starting values
  const character = await prisma.character.create({
    data: {
      userId: userId,
      name: 'UGT-Agent',
      shipName: 'Neural-Net-1',
      currentSystem: 1,
      creditsHigh: 0,
      creditsLow: 1000,      // Starting credits: 1,000
      rank: 'LIEUTENANT',
      score: 0,
      missionType: 0,
      cargoPods: 0,
      destination: 0,
    },
  });

  characterId = character.id;

  // Create ship with original Apple II starting values
  await prisma.ship.create({
    data: {
      characterId: character.id,
      hullStrength: 5,      hullCondition: 9,
      driveStrength: 5,     driveCondition: 9,
      cabinStrength: 1,     cabinCondition: 9,
      lifeSupportStrength: 5, lifeSupportCondition: 9,
      weaponStrength: 1,    weaponCondition: 9,
      navigationStrength: 5, navigationCondition: 9,
      roboticsStrength: 1,  roboticsCondition: 9,
      shieldStrength: 1,    shieldCondition: 9,
      fuel: 50,             // Starting fuel: 50
      cargoPods: 0,
      maxCargoPods: 0,
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

  // Check termination conditions
  const isConqueror = state.character.score >= 10000;
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
      const actionId = cmd.action_id ?? 0;
      response = await stepGame(actionId);
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
