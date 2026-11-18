package study.shipping;

/** Stateful quotation/confirmation protocol, intentionally not a counter. */
public final class ShipmentSession {
    private String state = "DRAFT";
    private int quotedCents;
    private String receipt;

    public int requestQuote(String zone, int grams, boolean express) {
        requireState("DRAFT");
        int cents = ShippingRules.quote(zone, grams, express);
        quotedCents = cents;
        state = "QUOTED";
        return cents;
    }

    public String confirm(int offeredCents, String orderId) {
        requireState("QUOTED");
        if (offeredCents != quotedCents) {
            throw new IllegalArgumentException("price-mismatch");
        }
        if (orderId == null || orderId.length() < 3) {
            throw new IllegalArgumentException("invalid-order-id");
        }
        receipt = orderId + ":" + quotedCents;
        state = "CONFIRMED";
        return receipt;
    }

    public void reset() {
        if ("CONFIRMED".equals(state)) {
            throw new IllegalStateException("already-confirmed");
        }
        quotedCents = 0;
        state = "DRAFT";
    }

    private void requireState(String expected) {
        if (!expected.equals(state)) {
            throw new IllegalStateException("state-" + state);
        }
    }
}
