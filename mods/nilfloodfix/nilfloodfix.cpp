// nilfloodfix: the Egyptians' "Nile flood" sacrifice doubles their corn, as it does for the Bavarians.
//
// The sacrifice (sacrifice_nilfloodEgypt in sacrifices.lua, Effect_CornDoubleProduction) sets the owner's sacrifice
// modifier flag 12 for its duration. The amount a building produces is read through
// ai::logic::SacrificePlayerTableRef::GetEntryWithModifiers S 00661c50, which passes a product to
// SacrificeModifiers::ApplyAmountDoubling S 00663450 (doubled while flag 12 > 0) only when its good id is the literal
// 0x17626a03, corn (S 00661c6f). Egyptian farms (farmClay) produce egyptCorn, 0x4a852f49 (Goods.lua), so the
// Egyptians pay for the sacrifice and get nothing. This mod gives egyptCorn the same branch the game gives corn.
// Callers: NVillage::Production::DeliverProducts S 00565990 (what goes into the stock), S2CG::Building::Update
// S 006abcf0 and NMovie::PutDownPackage::Update S 0077a8e0; all three see the doubled amount, as they do for corn.
// Changes the match: every player needs it (SERVER).
#include <sadkmod/game/sadk_noav/fn/ai.hpp>
#include <sadkmod/sadkmod.hpp>

#include <cstdint>

namespace game = sadk::game;
namespace fn = sadk::game::fn;

namespace {

using GetEntryWithModifiers = sadk::Hook<fn::ai::logic::SacrificePlayerTableRef::GetEntryWithModifiers>;

constexpr std::int32_t kEgyptCorn = 0x4a852f49;

std::int32_t *SADK_THISCALL get_entry_with_modifiers(game::ai::logic::SacrificePlayerTableRef *self,
                                                     std::int32_t *outPair, void *building, std::int32_t slot)
{
    auto *b = static_cast<game::NVillage::Building *>(building);
    if (*fn::ai::properties::BuildingProperty::GetGoods(b->property, slot) != kEgyptCorn)
        return GetEntryWithModifiers::original(self, outPair, building, slot);
    // The game's corn branch: the owner's modifiers, players[owner index].modifiers (S 00661c77..00661c8c).
    game::ai::logic::SacrificeModifiers *modifiers = &self->table->players[b->ownerPlayer->index].modifiers;
    return fn::ai::logic::SacrificeModifiers::ApplyAmountDoubling(modifiers, outPair, building, slot);
}

}  // namespace

bool nilfloodfix_start()
{
    bool ok = GetEntryWithModifiers::install(get_entry_with_modifiers);
    sadk::log(ok ? "the Nile flood doubles egyptCorn" : "nilfloodfix NOT active");
    return ok;
}

SADKMOD_MAIN(nilfloodfix_start, 1, SADKMOD_SERVER)
