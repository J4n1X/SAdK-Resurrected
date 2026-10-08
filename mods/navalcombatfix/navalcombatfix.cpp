// navalcombatfix: soldiers cross the water through their own player's harbours (attacks, colonies, defence) and ships
// pick up soldiers left with nowhere to go (CONCEPT.md; docs/navy-and-military.md §7). Changes the match simulation:
// every player of a match needs it (SERVER).
#include "navy.hpp"

bool combat_start();    // combat.cpp: soldiers cross the water through their own harbours
bool retreat_start();   // retreat.cpp: ships pick up soldiers left with nowhere to go
bool proximity_start(); // proximity.cpp: own routes count for the distance to the enemy (stripes, attackability)

// navalcombatfix.ini (navy.hpp, Settings).
void load_settings()
{
    sadk::Ini ini = sadk::mod_settings();
    navalcombatfix::Settings &s = navalcombatfix::g_settings;
    const char *section = "NavalCombatFix";
    s.attackersBySea = ini.get_bool(section, "AttackersBySea", s.attackersBySea);
    s.defendersBySea = ini.get_bool(section, "DefendersBySea", s.defendersBySea);
    s.attackFromOwnLanding = ini.get_bool(section, "AttackFromOwnLanding", s.attackFromOwnLanding);
    s.retreatPickup = ini.get_bool(section, "RetreatPickup", s.retreatPickup);
    s.proximityOverOwnRoutes = ini.get_bool(section, "ProximityOverOwnRoutes", s.proximityOverOwnRoutes);
    s.crossingDistance = ini.get_int(section, "CrossingDistance", s.crossingDistance);
    s.pickupTimeout = ini.get_int(section, "PickupTimeout", s.pickupTimeout);
    sadk::log("settings: attackers by sea %d, defenders by sea %d, attack from own landing %d, retreat pickup %d, "
              "proximity over own routes %d, crossing distance %d, pickup timeout %d",
              s.attackersBySea, s.defendersBySea, s.attackFromOwnLanding, s.retreatPickup, s.proximityOverOwnRoutes,
              s.crossingDistance, s.pickupTimeout);
}

bool navalcombatfix_start()
{
    load_settings();
    bool combat = combat_start();
    bool retreat = retreat_start();
    bool proximity = proximity_start();
    return combat && retreat && proximity;
}

SADKMOD_MAIN(navalcombatfix_start, 1, SADKMOD_SERVER)
