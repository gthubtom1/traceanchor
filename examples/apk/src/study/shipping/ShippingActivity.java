package study.shipping;

import android.app.Activity;
import android.os.Bundle;

public final class ShippingActivity extends Activity {
    private final ShipmentSession session = new ShipmentSession();
    private String observedReceipt;

    @Override
    public void onCreate(Bundle state) {
        super.onCreate(state);
        int price = session.requestQuote("LOCAL", 750, false);
        observedReceipt = session.confirm(price, "demo-order");
    }
}
