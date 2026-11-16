trigger CaseRoutingTier on Case (before insert, before update) {
    CaseRoutingTierHandler.apply(Trigger.new, Trigger.oldMap);
}
