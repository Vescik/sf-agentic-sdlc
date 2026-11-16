trigger CaseRoutingTrigger on Case (before insert, before update) {
    CaseRoutingHandler.applyRoutingTier(
        Trigger.new,
        Trigger.isUpdate ? Trigger.oldMap : null
    );
}
