package study.shipping;

/** Self-authored fixture. Integer cents and grams avoid floating-point ambiguity. */
public final class ShippingRules {
    public static int quote(String zone, int grams, boolean express) {
        if (grams <= 0 || grams > 20000) {
            throw new IllegalArgumentException("weight-out-of-range");
        }
        int base;
        if ("LOCAL".equals(zone)) {
            base = 350;
        } else if ("REMOTE".equals(zone)) {
            base = 900;
        } else {
            throw new IllegalArgumentException("unknown-zone");
        }
        int blocks = (grams + 499) / 500;
        int total = base + (blocks - 1) * 125;
        if (express) {
            if ("REMOTE".equals(zone) && grams > 5000) {
                throw new IllegalArgumentException("express-unavailable");
            }
            total += 600;
        }
        return total;
    }
}
