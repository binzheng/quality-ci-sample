package com.example.demo.todo;

import java.net.URI;
import java.util.List;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * TODO の REST API.
 */
@RestController
@RequestMapping("/api/todos")
public class TodoController {

    private final TodoService service;

    /**
     * コンストラクタ.
     *
     * @param service TODO サービス
     */
    public TodoController(TodoService service) {
        this.service = service;
    }

    /**
     * TODO 一覧を返す.
     *
     * @return TODO の一覧
     */
    @GetMapping
    public List<Todo> list() {
        return service.findAll();
    }

    /**
     * TODO を 1 件返す.
     *
     * @param id ID
     * @return TODO (存在しない場合 404)
     */
    @GetMapping("/{id}")
    public ResponseEntity<Todo> get(@PathVariable long id) {
        return ResponseEntity.of(service.findById(id));
    }

    /**
     * TODO を作成する.
     *
     * @param request 作成リクエスト
     * @return 作成した TODO (201)
     */
    @PostMapping
    public ResponseEntity<Todo> create(@RequestBody CreateTodoRequest request) {
        Todo todo = service.create(request.title());
        return ResponseEntity.created(URI.create("/api/todos/" + todo.id())).body(todo);
    }

    /**
     * TODO を完了状態にする.
     *
     * @param id ID
     * @return 更新後の TODO (存在しない場合 404)
     */
    @PostMapping("/{id}/complete")
    public ResponseEntity<Todo> complete(@PathVariable long id) {
        return ResponseEntity.of(service.complete(id));
    }

    /**
     * TODO を削除する.
     *
     * @param id ID
     * @return 204 (存在しない場合 404)
     */
    @DeleteMapping("/{id}")
    public ResponseEntity<Void> delete(@PathVariable long id) {
        return service.delete(id) ? ResponseEntity.noContent().build() : ResponseEntity.notFound().build();
    }

    /**
     * 入力エラーを 400 に変換する.
     *
     * @param e 例外
     * @return エラーメッセージ
     */
    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Map<String, String>> handleBadRequest(IllegalArgumentException e) {
        return ResponseEntity.badRequest().body(Map.of("error", e.getMessage()));
    }
}
