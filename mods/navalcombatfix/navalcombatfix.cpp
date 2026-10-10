// navalcombatfix: soldiers cross the water through their own player's harbours (attacks, colonies, defence) and ships
// pick up soldiers left with nowhere to go (CONCEPT.md; docs/navy-and-military.md §7). Changes the match simulation:
// every player of a match needs it (SERVER).
#include "navy.hpp"

#include <cstring>

bool combat_start();    // combat.cpp: soldiers cross the water through their own harbours
bool retreat_start();   // retreat.cpp: ships pick up soldiers left with nowhere to go
bool proximity_start(); // proximity.cpp: own routes count for the distance to the enemy (stripes, attackability)
bool invasion_start();  // invasion.cpp: scouting, "Prepare naval invasion", invasion ships
bool takeover_start();  // takeover.cpp: expeditions take ungarrisoned enemy harbours

namespace {

// ValidRetreatHarbors = own | neutral | friendly | all (case ignored); anything else keeps the default.
const char *const kRetreatHarborNames[] = {"own", "neutral", "friendly", "all"};

navalcombatfix::RetreatHarbors parse_retreat_harbors(const std::string &value, navalcombatfix::RetreatHarbors fallback)
{
    for (int i = 0; i < 4; ++i)
        if (!_stricmp(value.c_str(), kRetreatHarborNames[i])) return static_cast<navalcombatfix::RetreatHarbors>(i);
    if (!value.empty()) sadk::log("ValidRetreatHarbors: unknown value \"%s\", using the default", value.c_str());
    return fallback;
}

}  // namespace

// navalcombatfix.ini (navy.hpp, Settings).
void load_settings()
{
    sadk::Ini ini = sadk::mod_settings();
    navalcombatfix::Settings &s = navalcombatfix::g_settings;
    const char *section = "NavalCombatFix";
    s.attackersBySea = ini.get_bool(section, "AttackersBySea", s.attackersBySea);
    s.defendersBySea = ini.get_bool(section, "DefendersBySea", s.defendersBySea);
    s.attackFromOwnLanding = ini.get_bool(section, "AttackFromOwnLanding", s.attackFromOwnLanding);
    s.retreatHarbors = parse_retreat_harbors(ini.get(section, "ValidRetreatHarbors"), s.retreatHarbors);
    s.proximityOverOwnRoutes = ini.get_bool(section, "ProximityOverOwnRoutes", s.proximityOverOwnRoutes);
    s.neutralLandings = ini.get_bool(section, "NeutralLandings", s.neutralLandings);
    s.crossingDistance = ini.get_int(section, "CrossingDistance", s.crossingDistance);
    s.pickupTimeout = ini.get_int(section, "PickupTimeout", s.pickupTimeout);
    s.shipLostOnDefeat = ini.get_bool(section, "ShipLostOnDefeat", s.shipLostOnDefeat);
    s.landingReach = ini.get_int(section, "LandingReach", s.landingReach);
    s.harborMustHaveGarrison = ini.get_bool(section, "HarborMustHaveGarrison", s.harborMustHaveGarrison);
    sadk::log("settings: attackers by sea %d, defenders by sea %d, attack from own landing %d, retreat harbours %s, "
              "proximity over own routes %d, neutral landings %d, crossing distance %d, pickup timeout %d, ship lost on defeat %d, "
              "landing reach %d, harbour must have garrison %d",
              s.attackersBySea, s.defendersBySea, s.attackFromOwnLanding,
              kRetreatHarborNames[static_cast<int>(s.retreatHarbors)], s.proximityOverOwnRoutes,
              s.neutralLandings, s.crossingDistance, s.pickupTimeout, s.shipLostOnDefeat,
              s.landingReach, s.harborMustHaveGarrison);
}

bool navalcombatfix_start()
{
    load_settings();
    bool combat = combat_start();
    bool retreat = retreat_start();
    bool proximity = proximity_start();
    bool invasion = invasion_start();
    bool takeover = takeover_start();
    return combat && retreat && proximity && invasion && takeover;
}

SADKMOD_MAIN(navalcombatfix_start, 1, SADKMOD_SERVER)
