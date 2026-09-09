package com.hector.logistics

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.viewmodel.compose.viewModel
import org.json.JSONObject
import java.util.UUID

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme(colorScheme = darkColorScheme(primary = Color(0xFFB8D887),
                background = Color(0xFF101510), surface = Color(0xFF1B221C))) {
                Surface(Modifier.fillMaxSize()) { HectorScreen() }
            }
        }
    }
}

private val statuses = linkedMapOf("NEW" to "Новый", "ACCEPTED" to "Принят",
    "WAITING_RESOURCES" to "Ожидает ресурсов", "IN_PRODUCTION" to "В производстве",
    "READY" to "Готов", "IN_DELIVERY" to "Доставляется", "COMPLETED" to "Выполнен",
    "CANCELLED" to "Отменён", "REJECTED" to "Отклонён", "ON_HOLD" to "Приостановлен")
private val units = linkedMapOf("item" to "Штуки", "crate" to "Ящики", "batch" to "Партии", "request" to "Запрос")
private fun JSONObject.id() = getLong("id")
private fun unit(row: JSONObject) = units[row.text("unit")] ?: row.text("unit")
private data class Field(val key: String, val label: String, val initial: String = "",
                         val number: Boolean = false, val choices: Map<String, String>? = null,
                         val required: Boolean = true)
private data class Action(val title: String, val path: String, val fields: List<Field>,
                          val base: JSONObject = JSONObject(), val method: String = "POST",
                          val orderPicker: Boolean = false, val description: String = "")

@Composable
private fun HectorScreen(model: HectorModel = viewModel()) {
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_START) model.foreground(true)
            if (event == Lifecycle.Event.ON_STOP) model.foreground(false)
        }
        lifecycle.addObserver(observer)
        if (lifecycle.currentState.isAtLeast(Lifecycle.State.STARTED)) model.foreground(true)
        onDispose { lifecycle.removeObserver(observer); model.foreground(false) }
    }
    var action by remember { mutableStateOf<Action?>(null) }
    var calcItem by remember { mutableStateOf<JSONObject?>(null) }
    BackHandler(enabled = model.detail != null) { model.closeOrder() }
    Column(Modifier.fillMaxSize().safeDrawingPadding().imePadding().padding(horizontal = 16.dp)) {
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("HECTOR", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold,
                modifier = Modifier.padding(vertical = 16.dp))
            if (model.person != null) TextButton(onClick = { action = null; calcItem = null; model.logout() }) { Text("Выйти") }
        }
        if (model.person == null) {
            Login(model)
        } else {
            Text("${model.person!!.text("name")} · ${if (model.online) "Обновления подключены" else "Подключение обновлений…"}",
                style = MaterialTheme.typography.bodySmall)
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Page.entries.forEach { p -> FilterChip(selected = model.page == p,
                    onClick = { model.select(p); calcItem = null }, label = { Text(p.label) }) }
            }
            if (model.detail != null) {
                OrderDetail(model, model.detail!!, { action = it })
            } else {
                if (model.page in setOf(Page.ORDERS, Page.STOCK, Page.CATALOG)) Row(Modifier.fillMaxWidth()) {
                    OutlinedTextField(value = model.query, onValueChange = { model.query = it },
                        label = { Text("Поиск") }, singleLine = true, modifier = Modifier.weight(1f))
                    TextButton(onClick = model::search, modifier = Modifier.padding(top = 12.dp)) { Text("Найти") }
                }
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    TextButton(onClick = { model.reload() }) { Text("Обновить") }
                    if (model.page == Page.STOCK && model.role in setOf("ADMIN", "MANAGER")) TextButton(onClick = {
                        action = Action("Новый склад", "/api/v1/inventory/warehouses", listOf(Field("name", "Название склада")))
                    }) { Text("+ Склад") }
                    if (model.page == Page.TASKS && model.canTasks) TextButton(onClick = {
                        model.loadOrderChoices()
                        action = Action("Новая задача", "/api/v1/production/tasks", listOf(
                            Field("title", "Название этапа"), Field("quantity", "План", "1", true),
                            Field("unit", "Единица", "item", choices = units.filterKeys { it != "request" })),
                            base = payload("request_key" to UUID.randomUUID().toString()), orderPicker = true)
                    }) { Text("+ Задача") }
                }
                LazyColumn(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp),
                    contentPadding = PaddingValues(bottom = 24.dp)) {
                    if (model.rows.isEmpty()) item { Text("Записей пока нет. Можно обновить список.",
                        modifier = Modifier.padding(vertical = 24.dp)) }
                    model.calculation?.let { plan -> item { Card(Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(16.dp)) { Heading("Результат расчёта"); Calculation(plan) }
                    } } }
                    items(model.rows, key = { "${model.page}:${it.id()}" }) { row ->
                        Card(Modifier.fillMaxWidth()) {
                            Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                                when (model.page) {
                                    Page.ORDERS -> {
                                        Heading("№${row.text("public_number")} · ${row.text("customer_name")}")
                                        Text(row.text("status_label"), color = MaterialTheme.colorScheme.primary)
                                        row.rows("items").forEach { Text("${it.text("name")} × ${it.text("quantity")} ${unit(it)}") }
                                        Text(row.text("delivery_location"))
                                        TextButton(onClick = { model.openOrder(row) }) { Text("Открыть заказ") }
                                    }
                                    Page.STOCK -> {
                                        Heading(row.text("name"))
                                        Text(model.warehouses[row.optLong("warehouse_id")] ?: "Склад")
                                        Text("${unit(row)} · Доступно ${row.text("available")}")
                                        Text("На складе ${row.text("actual")} · Резерв ${row.text("reserved")}")
                                        if (model.canStock) {
                                            TextButton(onClick = {
                                                action = Action("Остаток: ${row.text("name")}", "/api/v1/inventory/stock/${row.id()}",
                                                    listOf(Field("actual", "Фактическое количество", row.text("actual"), true),
                                                        Field("reason", "Причина изменения")), payload("version" to row.getInt("version")), "PATCH")
                                            }) { Text("Изменить остаток") }
                                            TextButton(onClick = {
                                                model.loadOrderChoices()
                                                action = Action("Зарезервировать: ${row.text("name")}", "/api/v1/inventory/reservations",
                                                    listOf(Field("quantity", "Количество (${unit(row)})", "1", true)),
                                                    payload("stock_id" to row.id(), "request_key" to UUID.randomUUID().toString()), orderPicker = true)
                                            }) { Text("Зарезервировать") }
                                        }
                                    }
                                    Page.RESERVATIONS -> {
                                        Heading(row.text("name"))
                                        Text("${row.text("warehouse")} · ${row.text("quantity")} ${unit(row)}")
                                        Text(when (row.text("state")) { "ACTIVE" -> "Активен"; "CONSUMED" -> "Списан"; else -> "Освобождён" })
                                        TextButton(onClick = { model.openOrder(payload("id" to row.getLong("order_id"))) }) { Text("Заказ") }
                                        if (model.canReserveFinish && row.text("state") == "ACTIVE") {
                                            Row {
                                                listOf("release" to "Освободить", "consume" to "Списать").forEach { (code, label) ->
                                                    TextButton(onClick = { action = Action(label + " резерв", "/api/v1/inventory/reservations/${row.id()}",
                                                        emptyList(), payload("version" to row.getInt("version"), "action" to code),
                                                        description = if (code == "consume") "Подтвердите фактическую выдачу ${row.text("quantity")} ${unit(row)}. Остаток уменьшится." else "Количество снова станет доступно на складе.") }) { Text(label) }
                                                }
                                            }
                                        }
                                    }
                                    Page.TASKS -> {
                                        Heading(row.text("title"))
                                        Text("Готово ${row.text("completed")} / ${row.text("quantity")} ${unit(row)}")
                                        Text(when (row.text("status")) { "PLANNED" -> "Запланировано"; "IN_PROGRESS" -> "В работе"; "COMPLETED" -> "Завершено"; else -> "Отменено" })
                                        TextButton(onClick = { model.openOrder(payload("id" to row.getLong("order_id"))) }) { Text("Заказ") }
                                        if (model.canTasks && row.text("status") in setOf("PLANNED", "IN_PROGRESS")) {
                                            Row(Modifier.horizontalScroll(rememberScrollState())) {
                                                if (row.text("assigned_user_id").isEmpty()) TextButton(onClick = {
                                                    action = Action("Принять задачу", "/api/v1/production/tasks/${row.id()}", emptyList(),
                                                        payload("version" to row.getInt("version"), "action" to "claim"))
                                                }) { Text("Принять") }
                                                TextButton(onClick = { action = Action("Готовность задачи", "/api/v1/production/tasks/${row.id()}",
                                                    listOf(Field("completed", "Всего изготовлено", row.text("completed"), true)),
                                                    payload("version" to row.getInt("version"), "action" to "progress"),
                                                    description = "Введите общее количество готового, а не прибавку.") }) { Text("Готовность") }
                                                TextButton(onClick = { action = Action("Отменить задачу", "/api/v1/production/tasks/${row.id()}",
                                                    emptyList(), payload("version" to row.getInt("version"), "action" to "cancel"), description = row.text("title")) }) { Text("Отменить") }
                                            }
                                        }
                                    }
                                    Page.CATALOG -> {
                                        Heading(row.text("name")); Text(row.text("api_name"))
                                        TextButton(onClick = { calcItem = row }) { Text("Рассчитать") }
                                        if (model.canStock) TextButton(onClick = {
                                            action = Action("Добавить на склад", "/api/v1/inventory/stock", listOf(
                                                Field("warehouse_id", "Склад", number = true, choices = model.warehouses.mapKeys { it.key.toString() }),
                                                Field("unit", "Единица", "item", choices = units.filterKeys { it in setOf("item", "crate") })),
                                                payload("item_id" to row.id()), description = "${row.text("name")}. Новая позиция создаётся с нулевым остатком. Укажите фактическое количество на вкладке «Склад».")
                                        }) { Text("Добавить на склад") }
                                    }
                                }
                            }
                        }
                    }
                    if (model.more) item { OutlinedButton(onClick = { model.reload(true) }, modifier = Modifier.fillMaxWidth()) { Text("Загрузить ещё") } }
                }
            }
        }
        if (model.busy) LinearProgressIndicator(Modifier.fillMaxWidth())
        model.error?.let { message ->
            Text(message, color = MaterialTheme.colorScheme.error, modifier = Modifier.heightIn(max = 140.dp).verticalScroll(rememberScrollState()))
            TextButton(onClick = { model.error = null }) { Text("Закрыть сообщение") }
        }
    }
    action?.let { value -> ActionDialog(value, model, { action = null }) }
    calcItem?.let { item -> CalculatorDialog(item, model) { calcItem = null } }
}

@Composable
private fun Heading(text: String) { Text(text, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold) }

@Composable
private fun Login(model: HectorModel) {
    Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        Text("Логистика клана", style = MaterialTheme.typography.headlineSmall)
        Text("Заказы, склад и производство на вашем сервере.")
        OutlinedTextField(value = model.address, onValueChange = { model.address = it }, label = { Text("HTTPS-адрес") },
            singleLine = true, enabled = !model.busy, modifier = Modifier.fillMaxWidth(), keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri))
        OutlinedTextField(value = model.loginToken, onValueChange = { model.loginToken = it }, label = { Text("Персональный ключ") },
            singleLine = true, enabled = !model.busy, modifier = Modifier.fillMaxWidth(), visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password, autoCorrectEnabled = false))
        Button(onClick = model::login, enabled = !model.busy, modifier = Modifier.fillMaxWidth()) { Text("Войти") }
        Text("Ключ хранится на этом устройстве в зашифрованном виде. Кнопка «Выйти» удаляет его.", style = MaterialTheme.typography.bodySmall)
    }
}

@Composable
private fun ColumnScope.OrderDetail(model: HectorModel, row: JSONObject, show: (Action) -> Unit) {
    Column(Modifier.weight(1f).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        TextButton(onClick = model::closeOrder) { Text("← К списку") }
        Heading("Заказ №${row.text("public_number")}")
        Text(row.text("customer_name")); Text(row.text("status_label"), color = MaterialTheme.colorScheme.primary)
        Text("Доставка: ${row.text("delivery_location")}")
        if (row.text("comment").isNotBlank()) Text(row.text("comment"))
        row.rows("items").forEach {
            Heading("${it.text("name")} × ${it.text("quantity")} ${unit(it)}")
            it.optJSONObject("calculation")?.let { plan -> Calculation(plan) }
        }
        if (model.canOrders && row.has("version")) {
            if (row.text("status") == "NEW") Button(onClick = { show(Action("Принять заказ", "/api/v1/orders/${row.id()}/accept",
                emptyList(), payload("version" to row.getInt("version")))) }) { Text("Принять заказ") }
            OutlinedButton(onClick = { show(Action("Изменить статус", "/api/v1/orders/${row.id()}/status", listOf(
                Field("status", "Статус", row.text("status"), choices = statuses), Field("reason", "Причина / комментарий", required = false)),
                payload("version" to row.getInt("version")))) }) { Text("Изменить статус") }
            OutlinedButton(onClick = { show(Action("Заметка сотрудникам", "/api/v1/orders/${row.id()}/notes",
                listOf(Field("content", "Текст заметки")))) }) { Text("Добавить заметку") }
        }
        TextButton(onClick = { model.openOrder(row) }) { Text("Обновить карточку") }
        Heading("Заметки")
        row.rows("notes").forEach { Text("${it.text("author")}: ${it.text("content")}") }
        Heading("История")
        row.rows("history").forEach { Text("${it.text("at").take(19).replace('T', ' ')} · ${it.text("actor")}\n${it.text("action")}",
            style = MaterialTheme.typography.bodySmall) }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun Choice(label: String, value: String, choices: Map<String, String>, change: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { expanded = true }, modifier = Modifier.fillMaxWidth()) { Text("$label: ${choices[value] ?: "Выберите"}") }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }, modifier = Modifier.heightIn(max = 320.dp)) {
            choices.forEach { (key, text) -> DropdownMenuItem(text = { Text(text) }, onClick = { change(key); expanded = false }) }
        }
    }
}

@Composable
private fun ActionDialog(action: Action, model: HectorModel, dismiss: () -> Unit) {
    val values = remember(action) { mutableStateMapOf<String, String>().apply { action.fields.forEach { put(it.key, it.initial) } } }
    var order by remember(action) { mutableStateOf("") }
    var invalid by remember(action) { mutableStateOf<String?>(null) }
    AlertDialog(onDismissRequest = { if (!model.busy) dismiss() }, title = { Text(action.title) },
        text = { Column(Modifier.verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (action.description.isNotEmpty()) Text(action.description)
            if (action.orderPicker) Choice("Заказ", order, model.orderChoices.associate { it.id().toString() to "№${it.text("public_number")} · ${it.text("customer_name")}" }) { order = it }
            action.fields.forEach { f ->
                if (f.choices != null) Choice(f.label, values[f.key].orEmpty(), f.choices) { values[f.key] = it }
                else OutlinedTextField(value = values[f.key].orEmpty(), onValueChange = { values[f.key] = it }, label = { Text(f.label) },
                    enabled = !model.busy, keyboardOptions = KeyboardOptions(keyboardType = if (f.number) KeyboardType.Number else KeyboardType.Text))
            }
            (invalid ?: model.error)?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        } }, confirmButton = { TextButton(enabled = !model.busy, onClick = {
            val missing = action.fields.any { (it.required && values[it.key].isNullOrBlank()) || (it.number && values[it.key]?.toIntOrNull() == null) }
            if (missing || (action.orderPicker && order.isEmpty())) { invalid = "Заполните поля и выберите заказ." }
            else {
                invalid = null
                val body = JSONObject(action.base.toString())
                action.fields.forEach { f -> body.put(f.key, if (f.number) values[f.key]!!.toInt() else values[f.key]!!.trim()) }
                if (action.orderPicker) body.put("order_id", order.toLong())
                model.mutate(action.path, action.method, body, dismiss)
            }
        }) { Text("Подтвердить") } }, dismissButton = { TextButton(enabled = !model.busy, onClick = dismiss) { Text("Назад") } })
}

@Composable
private fun CalculatorDialog(item: JSONObject, model: HectorModel, dismiss: () -> Unit) {
    var quantity by remember { mutableStateOf("1") }
    var selectedUnit by remember { mutableStateOf("item") }
    var recipe by remember { mutableStateOf("") }
    AlertDialog(onDismissRequest = dismiss, title = { Text(item.text("name")) }, text = {
        Column {
            OutlinedTextField(value = quantity, onValueChange = { quantity = it }, label = { Text("Количество") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number))
            Choice("Единица", selectedUnit, units.filterKeys { it in setOf("item", "crate") }) { selectedUnit = it }
            Choice("Рецепт цепочки", recipe, mapOf("" to "Автоматически") + item.rows("recipes").associate { it.text("key") to it.text("building") }) { recipe = it }
        }
    }, confirmButton = { TextButton(enabled = (quantity.toIntOrNull() ?: 0) in 1..100000 && !model.busy, onClick = {
        model.calculate(item, quantity.toInt(), selectedUnit, recipe); dismiss()
    }) { Text("Рассчитать") } }, dismissButton = { TextButton(onClick = dismiss) { Text("Назад") } })
}

@Composable
private fun Calculation(plan: JSONObject) {
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("${plan.text("name")} · ${plan.text("requested_amount")} ${units[plan.text("requested_unit")] ?: plan.text("requested_unit")}")
        plan.rows("methods").forEach { method ->
            Heading(method.text("building").ifEmpty { method.text("recipe_key") })
            Text("Выпуск: ${method.text("actual_output")} ${units[method.text("output_unit")] ?: method.text("output_unit")} · Партий: ${method.text("batches")}")
            listOf("materials" to "Материалы", "base_resources" to "Базовые ресурсы", "unresolved_resources" to "Нужно уточнить").forEach { (key, title) ->
                method.optJSONObject(key)?.takeIf { it.length() > 0 }?.let { values ->
                    Text(title, fontWeight = FontWeight.SemiBold)
                    values.keys().forEach { name -> Text("${method.optJSONObject("material_labels")?.optString(name, name) ?: name}: ${values.opt(name)}") }
                }
            }
            method.optJSONArray("notes")?.let { notes ->
                for (index in 0 until notes.length()) Text(notes.getString(index), style = MaterialTheme.typography.bodySmall)
            }
        }
        if (plan.rows("methods").isEmpty()) Text("Для этого предмета нет доступного расчёта.")
    }
}
