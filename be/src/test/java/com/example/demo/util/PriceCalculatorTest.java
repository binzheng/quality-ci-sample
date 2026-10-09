package com.example.demo.util;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.math.BigDecimal;
import org.junit.jupiter.api.Test;

class PriceCalculatorTest {

    @Test
    void appliesStandardTax() {
        assertThat(PriceCalculator.total(new BigDecimal("1000"), 2, false)).isEqualByComparingTo("2200");
    }

    @Test
    void appliesReducedTax() {
        assertThat(PriceCalculator.total(new BigDecimal("1000"), 2, true)).isEqualByComparingTo("2160");
    }

    @Test
    void appliesBulkDiscount() {
        // 100 * 10 = 1000 → 5% 割引 950 → 税込 1045
        assertThat(PriceCalculator.total(new BigDecimal("100"), 10, false)).isEqualByComparingTo("1045");
    }

    @Test
    void roundsDown() {
        // 99 * 1.1 = 108.9 → 108
        assertThat(PriceCalculator.total(new BigDecimal("99"), 1, false)).isEqualByComparingTo("108");
    }

    @Test
    void rejectsInvalidInput() {
        assertThatThrownBy(() -> PriceCalculator.total(null, 1, false))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PriceCalculator.total(new BigDecimal("-1"), 1, false))
                .isInstanceOf(IllegalArgumentException.class);
        assertThatThrownBy(() -> PriceCalculator.total(BigDecimal.TEN, -1, false))
                .isInstanceOf(IllegalArgumentException.class);
    }
}
