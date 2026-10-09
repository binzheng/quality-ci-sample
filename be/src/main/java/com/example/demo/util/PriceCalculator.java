package com.example.demo.util;

import java.math.BigDecimal;
import java.math.RoundingMode;

/**
 * 税込金額を計算するユーティリティ.
 */
public final class PriceCalculator {

    private static final BigDecimal TAX_RATE = new BigDecimal("0.10");

    private static final BigDecimal REDUCED_TAX_RATE = new BigDecimal("0.08");

    private static final int BULK_THRESHOLD = 10;

    private static final BigDecimal BULK_DISCOUNT_RATE = new BigDecimal("0.05");

    private PriceCalculator() {
        // utility class
    }

    /**
     * 税込合計金額を計算する (1 円未満切り捨て).
     *
     * <p>数量が 10 以上の場合は 5% 割引を適用する.</p>
     *
     * @param unitPrice  単価 (0 以上)
     * @param quantity   数量 (0 以上)
     * @param reducedTax 軽減税率 (8%) を適用する場合 true
     * @return 税込合計金額
     * @throws IllegalArgumentException 単価または数量が不正な場合
     */
    public static BigDecimal total(BigDecimal unitPrice, int quantity, boolean reducedTax) {
        if (unitPrice == null || unitPrice.signum() < 0) {
            throw new IllegalArgumentException("unitPrice must be zero or positive");
        }
        if (quantity < 0) {
            throw new IllegalArgumentException("quantity must be zero or positive");
        }
        BigDecimal subtotal = unitPrice.multiply(BigDecimal.valueOf(quantity));
        if (quantity >= BULK_THRESHOLD) {
            subtotal = subtotal.subtract(subtotal.multiply(BULK_DISCOUNT_RATE));
        }
        BigDecimal rate = reducedTax ? REDUCED_TAX_RATE : TAX_RATE;
        return subtotal.add(subtotal.multiply(rate)).setScale(0, RoundingMode.DOWN);
    }
}
