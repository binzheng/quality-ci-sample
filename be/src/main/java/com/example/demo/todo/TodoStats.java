package com.example.demo.todo;

/**
 * TODO の件数集計.
 *
 * @param total     全件数
 * @param done      完了件数
 * @param remaining 未完了件数
 */
public record TodoStats(int total, int done, int remaining) {
}
