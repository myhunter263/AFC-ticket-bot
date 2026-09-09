package com.hector.logistics

import android.app.Application
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import okhttp3.WebSocket
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder

enum class Page(val label: String, val path: String) {
    ORDERS("Заказы", "/api/v1/orders"), STOCK("Склад", "/api/v1/inventory/stock"),
    RESERVATIONS("Резервы", "/api/v1/inventory/reservations"),
    TASKS("Производство", "/api/v1/production/tasks"), CATALOG("Калькулятор", "/api/v1/catalog")
}

class HectorModel(app: Application) : AndroidViewModel(app) {
    private val credentials = Credentials(app)
    var address by mutableStateOf(credentials.address)
    var loginToken by mutableStateOf("")
    var person by mutableStateOf<JSONObject?>(null); private set
    var error by mutableStateOf<String?>(null)
    var busy by mutableStateOf(false); private set
    var online by mutableStateOf(false); private set
    var page by mutableStateOf(Page.ORDERS); private set
    var query by mutableStateOf("")
    var rows by mutableStateOf(emptyList<JSONObject>()); private set
    var more by mutableStateOf(false); private set
    var detail by mutableStateOf<JSONObject?>(null); private set
    var calculation by mutableStateOf<JSONObject?>(null); private set
    var orderChoices by mutableStateOf(emptyList<JSONObject>()); private set
    var warehouses by mutableStateOf(emptyMap<Long, String>()); private set
    private var api: HectorApi? = null
    private var socket: WebSocket? = null
    private var reconnect: Job? = null
    private var refreshJob: Job? = null
    private var cursor = 0L
    private var foreground = false
    private var generation = 0
    private var listQuery = ""
    val role: String get() = person?.text("role").orEmpty()
    val canOrders: Boolean get() = role in setOf("ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY")
    val canStock: Boolean get() = role in setOf("ADMIN", "MANAGER", "LOGISTICIAN")
    val canReserveFinish: Boolean get() = canStock || role == "DELIVERY"
    val canTasks: Boolean get() = role in setOf("ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION")

    init { credentials.load().takeIf { it.isNotBlank() }?.let { loginToken = it; login() } }

    private suspend fun guarded(work: suspend () -> Unit): Boolean = try {
        work(); true
    } catch (e: CancellationException) { throw e
    } catch (e: Exception) {
        if (e is ApiFailure && e.status == 401) logout()
        error = e.message ?: "Нет соединения с сервером. Попробуйте ещё раз."
        false
    }

    fun login() {
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            guarded {
                require(loginToken.trim().isNotEmpty()) { "Введите персональный ключ доступа." }
                val service = HectorApi(address, loginToken.trim())
                val me = JSONObject(service.request("/api/v1/me"))
                require(me.text("role") in setOf("ADMIN", "MANAGER", "LOGISTICIAN", "PRODUCTION", "DELIVERY", "VIEWER")) {
                    "Нужен персональный ключ сотрудника, а не ключ Discord-бота."
                }
                credentials.save(service.base, loginToken.trim())
                api = service; person = me; address = service.base; loginToken = ""
                reload(); connect()
            }
            busy = false
        }
    }

    fun logout() {
        generation++; credentials.clear(); reconnect?.cancel(); refreshJob?.cancel()
        socket?.cancel(); socket = null; api = null; person = null; online = false
        rows = emptyList(); detail = null; calculation = null; orderChoices = emptyList(); warehouses = emptyMap()
        cursor = 0; loginToken = ""
    }

    fun foreground(value: Boolean) {
        foreground = value
        if (value) { if (api != null) { reload(); connect() } }
        else { generation++; reconnect?.cancel(); socket?.cancel(); socket = null; online = false }
    }

    private fun connect() {
        val service = api ?: return
        if (!foreground || socket != null) return
        val current = generation
        socket = service.events(cursor, { event -> viewModelScope.launch {
            if (current != generation || !foreground) return@launch
            online = true
            if (event.has("id")) {
                cursor = maxOf(cursor, event.getLong("id"))
                refreshJob?.cancel()
                refreshJob = viewModelScope.launch { delay(350); reload() }
            }
        } }, { viewModelScope.launch {
            if (current != generation) return@launch
            online = false; socket = null
            if (foreground && api != null) {
                reconnect?.cancel()
                reconnect = viewModelScope.launch { delay(5000); connect() }
            }
        } })
    }

    fun select(value: Page) {
        page = value; query = ""; listQuery = ""; rows = emptyList(); detail = null
        calculation = null; more = false; reload()
    }

    fun search() { listQuery = query.trim(); reload() }

    fun reload(append: Boolean = false) {
        val service = api ?: return
        val selected = page
        val search = listQuery
        val offset = if (append) rows.size else 0
        val current = generation
        viewModelScope.launch { guarded {
            if (selected in setOf(Page.STOCK, Page.CATALOG)) {
                val names = JSONArray(service.request("/api/v1/inventory/warehouses")).objects()
                    .associate { it.getLong("id") to it.text("name") }
                if (generation == current) warehouses = names
            }
            val suffix = if (selected in setOf(Page.ORDERS, Page.STOCK, Page.CATALOG))
                "&search=" + URLEncoder.encode(search, "UTF-8") else ""
            val data = JSONArray(service.request(selected.path + "?limit=50&offset=$offset" + suffix)).objects()
            if (page == selected && search == listQuery && generation == current) {
                rows = if (append) (rows + data).distinctBy { it.getLong("id") } else data
                more = data.size == 50
            }
            val id = detail?.getLong("id")
            if (id != null) {
                val updated = JSONObject(service.request("/api/v1/orders/$id"))
                if (detail?.optLong("id") == id && generation == current) detail = updated
            }
        } }
    }

    fun openOrder(row: JSONObject) {
        val service = api ?: return
        val current = generation
        detail = row
        viewModelScope.launch { guarded {
            val loaded = JSONObject(service.request("/api/v1/orders/${row.getLong("id")}"))
            if (generation == current && detail?.optLong("id") == row.getLong("id")) detail = loaded
        } }
    }
    fun closeOrder() { detail = null }
    fun loadOrderChoices() {
        val service = api ?: return
        viewModelScope.launch { guarded {
            val data = mutableListOf<JSONObject>()
            var offset = 0
            do {
                val batch = JSONArray(service.request("/api/v1/orders?limit=200&offset=$offset")).objects()
                data += batch.filter { it.text("status") !in setOf("COMPLETED", "CANCELLED", "REJECTED") }
                offset += batch.size
            } while (batch.size == 200)
            orderChoices = data
        } }
    }

    fun mutate(path: String, method: String = "POST", body: JSONObject, done: () -> Unit) {
        val service = api ?: return
        if (busy) return
        busy = true; error = null
        viewModelScope.launch {
            val ok = guarded { service.request(path, method, body) }
            busy = false
            if (ok) { done(); reload() }
        }
    }

    fun calculate(item: JSONObject, quantity: Int, unit: String, recipe: String) {
        val service = api ?: return
        if (busy) return
        busy = true; calculation = null
        viewModelScope.launch {
            guarded {
                val choices = JSONObject()
                if (recipe.isNotEmpty()) choices.put(item.getString("api_id"), recipe)
                calculation = JSONObject(service.request("/api/v1/catalog/calculate", "POST",
                    payload("item_id" to item.getLong("id"), "quantity" to quantity,
                        "unit" to unit, "recipe_choices" to choices)))
            }
            busy = false
        }
    }

    override fun onCleared() { socket?.cancel(); super.onCleared() }
}
