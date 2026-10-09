package com.example.demo.todo;

import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Service;

/**
 * TODO をメモリ上で管理するサービス.
 */
@Service
public class TodoService {

    private final Map<Long, Todo> store = new ConcurrentHashMap<>();

    private final AtomicLong sequence = new AtomicLong();

    /**
     * すべての TODO を ID 順に返す.
     *
     * @return TODO の一覧
     */
    public List<Todo> findAll() {
        return store.values().stream()
                .sorted(Comparator.comparingLong(Todo::id))
                .toList();
    }

    /**
     * ID で TODO を検索する.
     *
     * @param id ID
     * @return 見つかった TODO
     */
    public Optional<Todo> findById(long id) {
        return Optional.ofNullable(store.get(id));
    }

    /**
     * TODO を作成する.
     *
     * @param title タイトル
     * @return 作成した TODO
     * @throws IllegalArgumentException タイトルが空の場合
     */
    public Todo create(String title) {
        Todo todo = new Todo(sequence.incrementAndGet(), title, false);
        store.put(todo.id(), todo);
        return todo;
    }

    /**
     * TODO を完了状態にする.
     *
     * @param id ID
     * @return 更新後の TODO (存在しない場合は空)
     */
    public Optional<Todo> complete(long id) {
        return Optional.ofNullable(store.computeIfPresent(id, (key, todo) -> todo.complete()));
    }

    /**
     * TODO を削除する.
     *
     * @param id ID
     * @return 削除した場合 true
     */
    public boolean delete(long id) {
        return store.remove(id) != null;
    }
}
