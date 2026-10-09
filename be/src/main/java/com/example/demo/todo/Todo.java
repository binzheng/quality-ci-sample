package com.example.demo.todo;

/**
 * TODO 項目.
 *
 * @param id    ID
 * @param title タイトル
 * @param done  完了フラグ
 */
public record Todo(long id, String title, boolean done) {

    /**
     * タイトルを検証する.
     *
     * @throws IllegalArgumentException タイトルが空の場合
     */
    public Todo {
        if (title == null || title.isBlank()) {
            throw new IllegalArgumentException("title must not be blank");
        }
    }

    /**
     * 完了状態にしたコピーを返す.
     *
     * @return 完了済みの TODO
     */
    public Todo complete() {
        return new Todo(id, title, true);
    }
}
