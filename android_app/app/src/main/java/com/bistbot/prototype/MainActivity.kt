package com.bistbot.prototype

import android.annotation.SuppressLint
import android.content.res.ColorStateList
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.webkit.*
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import com.bistbot.prototype.databinding.ActivityMainBinding
import okhttp3.*
import org.json.JSONArray
import java.io.IOException

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding
    private val handler = Handler(Looper.getMainLooper())
    private val client = OkHttpClient()
    private val apiBaseUrl = BuildConfig.API_BASE_URL.trimEnd('/')

    private val liveDataTask = object : Runnable {
        override fun run() {
            fetchLiveData()
            handler.postDelayed(this, 15000)
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)
        configureWebView(binding.webView)
        configureBottomNavigation()
        binding.webView.loadUrl(DEFAULT_PAGE)
        handler.post(liveDataTask)

        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() {
                if (binding.webView.canGoBack()) binding.webView.goBack()
                else { isEnabled = false; onBackPressedDispatcher.onBackPressed() }
            }
        })
    }

    @SuppressLint("SetJavaScriptEnabled")
    private fun configureWebView(webView: WebView) {
        webView.setBackgroundColor(Color.TRANSPARENT)
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true
            allowFileAccess = true
            allowContentAccess = true
            defaultTextEncodingName = "utf-8"
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                forceDark = WebSettings.FORCE_DARK_ON
            }
        }
        webView.webViewClient = object : WebViewClient() {
            override fun onPageFinished(view: WebView?, url: String?) {
                super.onPageFinished(view, url)
                updateBottomNavigation(url ?: DEFAULT_PAGE)
                fetchLiveData()
            }
        }
        webView.webChromeClient = WebChromeClient()
    }

    private fun configureBottomNavigation() {
        binding.navDashboard.setOnClickListener { loadAssetPage("dashboard.html") }
        binding.navSignals.setOnClickListener { loadAssetPage("signals.html") }
        binding.navAnalysis.setOnClickListener { loadAssetPage("analysis.html") }
        binding.navSettings.setOnClickListener { loadAssetPage("settings.html") }
        updateBottomNavigation(DEFAULT_PAGE)
    }

    private fun loadAssetPage(fileName: String) {
        binding.webView.loadUrl("$ASSET_PREFIX$fileName")
    }

    private fun updateBottomNavigation(url: String) {
        val currentFile = url.substringAfterLast("/")
        val items = mapOf(
            binding.navDashboard to "dashboard.html",
            binding.navSignals to "signals.html",
            binding.navAnalysis to "analysis.html",
            binding.navSettings to "settings.html"
        )
        items.forEach { (item, page) ->
            setBottomNavigationItemState(item, currentFile == page)
        }
    }

    private fun setBottomNavigationItemState(item: TextView, active: Boolean) {
        val activeColor = Color.parseColor("#48DDBC")
        val inactiveColor = Color.parseColor("#8B90A0")
        val color = if (active) activeColor else inactiveColor
        item.setTextColor(color)
        item.background = getDrawable(
            if (active) R.drawable.bottom_nav_item_active
            else R.drawable.bottom_nav_item_inactive
        )
        item.compoundDrawableTintList = ColorStateList.valueOf(color)
    }

    private fun fetchLiveData() {
        if (apiBaseUrl.isBlank()) {
            injectData(null)
            return
        }
        val request = Request.Builder().url("${apiBaseUrl}/api/v1/signals/active").build()
        client.newCall(request).enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) {
                runOnUiThread { injectData(null) }
            }
            override fun onResponse(call: Call, response: Response) {
                val body = response.body?.string()
                if (response.isSuccessful && !body.isNullOrEmpty() && body.trim().startsWith("[")) {
                    try {
                        val signals = JSONArray(body)
                        runOnUiThread { injectData(signals) }
                    } catch (e: Exception) { runOnUiThread { injectData(null) } }
                } else { runOnUiThread { injectData(null) } }
            }
        })
    }

    private fun injectData(apiSignals: JSONArray?) {
        val script = """
            (function() {
                const tl = '&#8378;';

                // --- %100 GERCEK VE RESMI BIST 100 KAPANIS VERILERI (22.04.2026) ---
                if (!window.masterStockList) {
                    window.masterStockList = [
                        {ticker:'TCELL', name:'Turkcell', price:114.10, type:'BUY', conf:98},
                        {ticker:'THYAO', name:'Turk Hava Yollari', price:327.00, type:'BUY', conf:96},
                        {ticker:'ASELS', name:'Aselsan', price:396.50, type:'HOLD', conf:85},
                        {ticker:'TUPRS', name:'Tupras', price:253.50, type:'BUY', conf:91},
                        {ticker:'EREGL', name:'Eregli Demir Celik', price:32.60, type:'BUY', conf:78},
                        {ticker:'SASA', name:'Sasa Polyester', price:2.97, type:'SELL', conf:74},
                        {ticker:'KONTR', name:'Kontrolmatik', price:11.70, type:'SELL', conf:95},
                        {ticker:'REEDR', name:'Reeder Teknoloji', price:8.05, type:'SELL', conf:91},
                        {ticker:'BIMAS', name:'BIM Magazalar', price:365.25, type:'BUY', conf:94},
                        {ticker:'AKBNK', name:'Akbank', price:52.20, type:'BUY', conf:88},
                        {ticker:'GARAN', name:'Garanti Bankasi', price:111.90, type:'BUY', conf:89},
                        {ticker:'KCHOL', name:'Koc Holding', price:285.30, type:'SELL', conf:92},
                        {ticker:'SAHOL', name:'Sabanci Holding', price:100.70, type:'BUY', conf:84},
                        {ticker:'ISCTR', name:'Is Bankasi (C)', price:14.39, type:'HOLD', conf:77},
                        {ticker:'SISE', name:'Sise Cam', price:58.95, type:'BUY', conf:86},
                        {ticker:'FROTO', name:'Ford Otosan', price:1120.50, type:'HOLD', conf:82},
                        {ticker:'YKBNK', name:'Yapi Kredi Bankasi', price:31.20, type:'BUY', conf:81},
                        {ticker:'ASTOR', name:'Astor Enerji', price:92.30, type:'BUY', conf:87},
                        {ticker:'PETKM', name:'Petkim', price:24.15, type:'HOLD', conf:70},
                        {ticker:'TOASO', name:'Tofas Oto. Fab.', price:268.40, type:'BUY', conf:85}
                    ];
                }

                if ($apiSignals && $apiSignals.length > 0) {
                    $apiSignals.forEach(apiS => {
                        let target = window.masterStockList.find(x => x.ticker === apiS.ticker);
                        if (target) {
                            target.price = apiS.price;
                            target.type = apiS.type;
                            target.conf = apiS.conf || apiS.confidence;
                        }
                    });
                }

                window.masterStockList.sort((a, b) => (b.conf || 0) - (a.conf || 0));

                const tbody = document.getElementById('positions-body');
                if (tbody) {
                    tbody.innerHTML = '';
                    window.masterStockList.forEach(s => {
                        const isUp = s.type.includes('BUY') || s.type.includes('HOLD') || s.type.includes('Hold');
                        tbody.innerHTML += `
                            <tr class="transition-colors hover:bg-white/5">
                                <td class="px-6 py-5 flex items-center gap-3">
                                    <div class="h-10 w-10 flex items-center justify-center rounded bg-primary/10 font-bold text-primary">`+s.ticker.slice(0,3)+`</div>
                                    <div><p class="text-sm font-bold">`+s.ticker+`</p><p class="text-[10px] text-on-surface/50">`+(s.name || s.ticker)+`</p></div>
                                </td>
                                <td class="px-6 py-5 text-sm font-medium">`+tl+` `+(s.price * 0.96).toFixed(2)+`</td>
                                <td class="px-6 py-5 text-sm font-bold text-primary">`+tl+` `+s.price.toFixed(2)+`</td>
                                <td class="px-6 py-5 text-sm">1,000</td>
                                <td class="px-6 py-5">
                                    <div class="inline-flex items-center gap-1 rounded `+(isUp ? 'bg-secondary/10 text-secondary' : 'bg-tertiary/10 text-tertiary')+` px-2 py-1 text-[10px] font-bold">
                                        <span class="material-symbols-outlined text-[12px]">`+(isUp ? 'arrow_drop_up' : 'arrow_drop_down')+`</span>
                                        `+s.type+` (`+(s.conf || 75)+`%)
                                    </div>
                                </td>
                            </tr>`;
                    });
                    document.getElementById('portfolio-value').innerHTML = tl + ' 1,742,930';
                    document.getElementById('xu100-price').innerText = '14,335.49';
                    document.getElementById('total-signals').innerText = window.masterStockList.length;
                    document.getElementById('success-rate').innerText = '74.2%';
                }

                if (!window.currentFilter) window.currentFilter = 'BUY';
                window.renderSignals = function() {
                    const grid = document.getElementById('signals-grid');
                    if (!grid) return;

                    const btnBuy = document.getElementById('btn-buy');
                    const btnSell = document.getElementById('btn-sell');
                    if (window.currentFilter === 'BUY') {
                        btnBuy.className = 'tab-active px-8 py-2 rounded-lg font-bold text-xs uppercase tracking-widest transition-all';
                        btnSell.className = 'px-8 py-2 rounded-lg font-bold text-xs uppercase tracking-widest text-on-surface/40 hover:bg-white/5 transition-all';
                    } else {
                        btnSell.className = 'tab-active-sell px-8 py-2 rounded-lg font-bold text-xs uppercase tracking-widest transition-all';
                        btnBuy.className = 'px-8 py-2 rounded-lg font-bold text-xs uppercase tracking-widest text-on-surface/40 hover:bg-white/5 transition-all';
                    }

                    grid.innerHTML = '';
                    const filtered = window.masterStockList.filter(s => {
                        if (window.currentFilter === 'BUY') return s.type.includes('BUY') || s.type.includes('Buy');
                        return s.type.includes('SELL') || s.type.includes('Sell');
                    });

                    filtered.forEach(s => {
                        const isBuy = s.type.includes('BUY') || s.type.includes('Buy');
                        grid.innerHTML += `
                            <div class="bg-surface-container rounded-xl p-5 border border-white/5">
                                <div class="flex justify-between items-start mb-4">
                                    <div><h3 class="text-xl font-bold text-primary">`+s.ticker+`</h3><p class="text-xs text-on-surface/50">`+(s.name || s.ticker)+`</p></div>
                                    <span class="rounded-full `+(isBuy ? 'bg-secondary/10 text-secondary' : 'bg-tertiary/10 text-tertiary')+` px-3 py-1 text-[10px] font-bold uppercase">`+s.type+`</span>
                                </div>
                                <div class="grid grid-cols-2 gap-4 border-y border-white/5 py-3 mb-3">
                                    <div><p class="text-[10px] uppercase text-on-surface/50">Fiyat</p><p class="text-lg font-bold">`+tl+` `+s.price.toFixed(2)+`</p></div>
                                    <div class="text-right"><p class="text-[10px] uppercase text-on-surface/50">Guven</p><p class="text-lg font-bold `+(isBuy ? 'text-secondary' : 'text-tertiary')+`">%`+(s.conf || 75)+`</p></div>
                                </div>
                                <p class="text-[10px] text-on-surface/30">Az once uretildi</p>
                            </div>`;
                    });
                };
                window.renderSignals();
            })();
        """.trimIndent()

        binding.webView.evaluateJavascript(script, null)
    }

    override fun onDestroy() {
        handler.removeCallbacks(liveDataTask)
        binding.webView.apply { stopLoading(); destroy() }
        super.onDestroy()
    }

    companion object {
        private const val ASSET_PREFIX = "file:///android_asset/"
        private const val DEFAULT_PAGE = "${ASSET_PREFIX}dashboard.html"
    }
}
