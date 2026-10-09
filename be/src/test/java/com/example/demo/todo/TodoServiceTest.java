package com.example.demo.todo;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class TodoServiceTest {

    private TodoService service;

    @BeforeEach
    void setUp() {
        service = new TodoService();
    }

    @Test
    void createAssignsSequentialIds() {
        Todo first = service.create("first");
        Todo second = service.create("second");

        assertThat(first.id()).isEqualTo(1L);
        assertThat(second.id()).isEqualTo(2L);
        assertThat(service.findAll()).extracting(Todo::title).containsExactly("first", "second");
    }

    @Test
    void createRejectsBlankTitle() {
        assertThatThrownBy(() -> service.create(" ")).isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void completeMarksTodoAsDone() {
        Todo todo = service.create("task");

        assertThat(service.complete(todo.id())).hasValueSatisfying(t -> assertThat(t.done()).isTrue());
        assertThat(service.findById(todo.id())).hasValueSatisfying(t -> assertThat(t.done()).isTrue());
    }

    @Test
    void completeReturnsEmptyForUnknownId() {
        assertThat(service.complete(99L)).isEmpty();
    }

    @Test
    void deleteRemovesTodo() {
        Todo todo = service.create("task");

        assertThat(service.delete(todo.id())).isTrue();
        assertThat(service.delete(todo.id())).isFalse();
        assertThat(service.findById(todo.id())).isEmpty();
    }
}
