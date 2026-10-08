// navalcombatfix: soldiers cross the water through their own player's harbours (attacks, colonies, defence) and ships
// pick up soldiers left with nowhere to go (CONCEPT.md; docs/navy-and-military.md §7). Changes the match simulation:
// every player of a match needs it (SERVER).
#include <sadkmod/sadkmod.hpp>

bool combat_start();    // combat.cpp: soldiers cross the water through their own harbours
bool retreat_start();   // retreat.cpp: ships pick up soldiers left with nowhere to go

bool navalcombatfix_start()
{
    bool combat = combat_start();
    bool retreat = retreat_start();
    return combat && retreat;
}

SADKMOD_MAIN(navalcombatfix_start, 1, SADKMOD_SERVER)
