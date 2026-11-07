/*
    AnyTranslate 0.1.0
    Real-time subtitle translation for PotPlayer using any LLM / translation API.

    SPDX-License-Identifier: MIT
    Copyright (c) 2026 RedHeartSecretMan
    Project: https://github.com/RedHeartSecretMan/any-translate

    Supported protocols:
      - OpenAI compatible  : /chat/completions
      - Anthropic          : /v1/messages
      - Google Gemini      : /v1beta/models/{model}:generateContent
      - Ollama native      : /api/chat
      - Custom JSON API    : user supplied URL + body template + JSON path
*/

// ===========================================================================
// 插件信息
// ===========================================================================

string GetTitle()
{
    return "{$CP949=AnyTranslate 번역$}{$CP950=AnyTranslate 翻譯$}{$CP0=AnyTranslate}";
}

string GetVersion()
{
    return "0.1.0";
}

string GetDesc()
{
    return "多 API 实时字幕翻译: OpenAI 兼容 / Anthropic / Gemini / Ollama / 自定义 JSON | https://github.com/RedHeartSecretMan/any-translate";
}

string GetLoginTitle()
{
    return "AnyTranslate 配置";
}

string GetLoginDesc()
{
    return "用户框: deepseek:deepseek-v4-flash 或 custom|<url>|<model>|<opts>；密码框: API Key（本机服务留空）";
}

string GetUserText()
{
    string suffix = "";
    if (!g_last_error.empty()) suffix = " [" + g_last_error + "]";
    return "服务: " + DescribeCurrentSpec() + suffix;
}

string GetPasswordText()
{
    return "API Key: " + MaskKey(CurrentKey());
}

// ===========================================================================
// 全局配置
// ===========================================================================

string DEFAULT_SPEC = "ollama:qwen3:4b";
string USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AnyTranslate/3.0";

string g_spec = "";
string g_key = "";
bool g_configured = false;
bool g_logged_out = false;
bool g_debug = false;
bool g_console_opened = false;

// 解析后的运行参数
string g_provider = "";
string g_proto = "openai";
string g_base = "";
string g_model = "";
string g_auth = "bearer";
string g_keyname = "";
string g_path = "";
string g_body_template = "";
string g_temperature = "0.2";
string g_max_tokens = "";
string g_probe = "models";
string g_extra_body = "";
string g_version = "2023-06-01";
bool g_minimal_body = false;

// 上下文 / 缓存
array<string> g_history;
int MAX_HISTORY = 4;
array<string> g_cache_keys;
array<string> g_cache_vals;
int CACHE_MAX = 64;
string g_last_key = "";

// 运行状态
uint g_last_tick = 0;
int g_fail_count = 0;
int FAIL_CLEAR = 5;
int g_http_status = 0;
string g_http_body = "";
bool g_path_found = false;
bool g_dst_rtl = false;
string g_last_error = "";
string g_last_dst = "";
string g_pending_log = "";

// ===========================================================================
// 服务商预设表
// ===========================================================================

array<string> P_ID =
{
    "openai", "deepseek", "moonshot", "zhipu", "qwen", "siliconflow",
    "openrouter", "groq", "xai", "mistral", "together",
    "lmstudio", "vllm", "ollama", "anthropic", "gemini", "custom"
};

array<string> P_BASE =
{
    "https://api.openai.com/v1",
    "https://api.deepseek.com/v1",
    "https://api.moonshot.cn/v1",
    "https://open.bigmodel.cn/api/paas/v4",
    "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "https://api.siliconflow.cn/v1",
    "https://openrouter.ai/api/v1",
    "https://api.groq.com/openai/v1",
    "https://api.x.ai/v1",
    "https://api.mistral.ai/v1",
    "https://api.together.ai/v1",
    "http://127.0.0.1:1234/v1",
    "http://127.0.0.1:8000/v1",
    "http://127.0.0.1:11434",
    "https://api.anthropic.com",
    "https://generativelanguage.googleapis.com",
    ""
};

array<string> P_MODEL =
{
    "gpt-5.6-terra",
    "deepseek-v4-flash",
    "kimi-k3.1-pro",
    "glm-5.3",
    "qwen-flash",
    "deepseek-ai/DeepSeek-V4-Flash",
    "openai/gpt-5.6-terra",
    "openai/gpt-oss-120b",
    "grok-4.20",
    "mistral-small-latest",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "",
    "",
    "qwen3:4b",
    "claude-sonnet-4-6",
    "gemini-3.5-flash",
    ""
};

array<string> P_PROTO =
{
    "openai", "openai", "openai", "openai", "openai", "openai",
    "openai", "openai", "openai", "openai", "openai",
    "openai", "openai", "ollama", "anthropic", "gemini", "openai"
};

array<string> P_AUTH =
{
    "bearer", "bearer", "bearer", "bearer", "bearer", "bearer",
    "bearer", "bearer", "bearer", "bearer", "bearer",
    "none", "none", "none", "x-api-key", "x-api-key", "bearer"
};

// 鉴权头名（空 = 按 auth 类型取默认值）
array<string> P_KEYNAME =
{
    "", "", "", "", "", "", "", "", "", "", "",
    "", "", "", "x-api-key", "x-goog-api-key", ""
};

// 追加到 OpenAI 兼容请求体尾部的厂商参数（含前导逗号；空 = 不追加）
// deepseek: 思考模式默认开启，字幕翻译必须关闭
// qwen / siliconflow: Qwen 系默认思考，关闭以降低延迟
array<string> P_EXTRA =
{
    "",
    ",\"thinking\":{\"type\":\"disabled\"}",
    "",
    "",
    ",\"enable_thinking\":false",
    ",\"enable_thinking\":false",
    "", "", "", "", "",
    "", "", "",
    "", "",
    ""
};

// ===========================================================================
// 语言表（菜单显示标签 / 提示词中的语言名 / 代码）
// ===========================================================================

array<string> L_CODE =
{
    "zh-CN", "zh-TW", "en", "ja", "ko", "de", "fr", "es", "ru", "pt",
    "it", "nl", "pl", "tr", "ar", "he", "hi", "bn", "th", "vi",
    "id", "ms", "tl", "uk", "cs", "sk", "hu", "ro", "bg", "hr",
    "sr", "sl", "el", "sv", "no", "da", "fi", "is", "lt", "lv",
    "et", "fa", "ur", "sw", "ca", "gl", "eu", "af", "ne", "si",
    "km", "lo", "my", "mn", "kk", "uz", "az", "hy", "ka", "sq",
    "be", "bs", "mk", "ga", "cy", "eo", "la", "lb", "mt", "mi",
    "mg", "ml", "mr", "pa", "so", "st", "su", "tg", "te", "ta",
    "ky", "gu"
};

array<string> L_LABEL =
{
    "简体中文", "繁體中文", "English", "日本語", "한국어", "Deutsch",
    "Français", "Español", "Русский", "Português", "Italiano", "Nederlands",
    "Polski", "Türkçe", "العربية", "עברית", "हिन्दी", "বাংলা", "ไทย",
    "Tiếng Việt", "Bahasa Indonesia", "Bahasa Melayu", "Filipino",
    "Українська", "Čeština", "Slovenčina", "Magyar", "Română", "Български",
    "Hrvatski", "Српски", "Slovenščina", "Ελληνικά", "Svenska", "Norsk",
    "Dansk", "Suomi", "Íslenska", "Lietuvių", "Latviešu", "Eesti", "فارسی",
    "اردو", "Kiswahili", "Català", "Galego", "Euskara", "Afrikaans", "नेपाली",
    "සිංහල", "ខ្មែរ", "ລາວ", "မြန်မာ", "Монгол", "Қазақ", "Oʻzbek",
    "Azərbaycan", "Հայերեն", "ქართული", "Shqip", "Беларуская", "Bosanski",
    "Македонски", "Gaeilge", "Cymraeg", "Esperanto", "Latina", "Lëtzebuergesch",
    "Malti", "Māori", "Malagasy", "മലയാളം", "मराठी", "ਪੰਜਾਬੀ", "Soomaali",
    "Sesotho", "Basa Sunda", "Тоҷикӣ", "తెలుగు", "தமிழ்", "Кыргызча", "ગુજરાતી"
};

array<string> L_PROMPT =
{
    "简体中文（Simplified Chinese）",
    "繁體中文（Traditional Chinese）",
    "英语（English）",
    "日语（Japanese）",
    "韩语（Korean）",
    "德语（German）",
    "法语（French）",
    "西班牙语（Spanish）",
    "俄语（Russian）",
    "葡萄牙语（Portuguese）",
    "意大利语（Italian）",
    "荷兰语（Dutch）",
    "波兰语（Polish）",
    "土耳其语（Turkish）",
    "阿拉伯语（Arabic）",
    "希伯来语（Hebrew）",
    "印地语（Hindi）",
    "孟加拉语（Bengali）",
    "泰语（Thai）",
    "越南语（Vietnamese）",
    "印尼语（Indonesian）",
    "马来语（Malay）",
    "菲律宾语（Filipino）",
    "乌克兰语（Ukrainian）",
    "捷克语（Czech）",
    "斯洛伐克语（Slovak）",
    "匈牙利语（Hungarian）",
    "罗马尼亚语（Romanian）",
    "保加利亚语（Bulgarian）",
    "克罗地亚语（Croatian）",
    "塞尔维亚语（Serbian）",
    "斯洛文尼亚语（Slovenian）",
    "希腊语（Greek）",
    "瑞典语（Swedish）",
    "挪威语（Norwegian）",
    "丹麦语（Danish）",
    "芬兰语（Finnish）",
    "冰岛语（Icelandic）",
    "立陶宛语（Lithuanian）",
    "拉脱维亚语（Latvian）",
    "爱沙尼亚语（Estonian）",
    "波斯语（Persian）",
    "乌尔都语（Urdu）",
    "斯瓦希里语（Swahili）",
    "加泰罗尼亚语（Catalan）",
    "加利西亚语（Galician）",
    "巴斯克语（Basque）",
    "南非荷兰语（Afrikaans）",
    "尼泊尔语（Nepali）",
    "僧伽罗语（Sinhala）",
    "高棉语（Khmer）",
    "老挝语（Lao）",
    "缅甸语（Burmese）",
    "蒙古语（Mongolian）",
    "哈萨克语（Kazakh）",
    "乌兹别克语（Uzbek）",
    "阿塞拜疆语（Azerbaijani）",
    "亚美尼亚语（Armenian）",
    "格鲁吉亚语（Georgian）",
    "阿尔巴尼亚语（Albanian）",
    "白俄罗斯语（Belarusian）",
    "波斯尼亚语（Bosnian）",
    "马其顿语（Macedonian）",
    "爱尔兰语（Irish）",
    "威尔士语（Welsh）",
    "世界语（Esperanto）",
    "拉丁语（Latin）",
    "卢森堡语（Luxembourgish）",
    "马耳他语（Maltese）",
    "毛利语（Maori）",
    "马达加斯加语（Malagasy）",
    "马拉雅拉姆语（Malayalam）",
    "马拉地语（Marathi）",
    "旁遮普语（Punjabi）",
    "索马里语（Somali）",
    "塞索托语（Sesotho）",
    "巽他语（Sundanese）",
    "塔吉克语（Tajik）",
    "泰卢固语（Telugu）",
    "泰米尔语（Tamil）",
    "吉尔吉斯语（Kyrgyz）",
    "古吉拉特语（Gujarati）"
};

// ===========================================================================
// 基础工具
// ===========================================================================

string Trimmed(const string &in s)
{
    string t = s;
    return t.Trim();
}

bool StartsWith(const string &in s, const string &in prefix)
{
    if (prefix.length() > s.length()) return false;
    return s.Left(prefix.length()) == prefix;
}

string StrReplaceAll(const string &in src, const string &in from, const string &in to)
{
    if (from.empty()) return src;
    string out = src;
    int pos = out.findFirst(from, 0);
    int guard = 0;
    while (pos >= 0 && guard < 5000)
    {
        out = out.Left(pos) + to + out.substr(pos + from.length());
        pos = out.findFirst(from, pos + to.length());
        guard++;
    }
    return out;
}

array<string> SplitStr(const string &in src, const string &in delim)
{
    array<string> parts;
    if (delim.empty())
    {
        parts.insertLast(src);
        return parts;
    }
    int start = 0;
    int idx = src.findFirst(delim, 0);
    int guard = 0;
    while (idx >= 0 && guard < 500)
    {
        parts.insertLast(src.substr(start, idx - start));
        start = idx + delim.length();
        idx = src.findFirst(delim, start);
        guard++;
    }
    parts.insertLast(src.substr(start));
    return parts;
}

string Truncate(const string &in s, int maxLen)
{
    if (s.length() <= maxLen) return s;
    return s.Left(maxLen) + "...";
}

string JsonEscape(const string &in input)
{
    // JSON 字符串不允许裸的 C0 控制字符；字幕里出现的控制字符直接剔除，
    // 只保留稍后需要短转义的 \t \n \r（HostRegExpRemove 只删第一个匹配，故循环）
    string clean = StripChars(input, "[\\x00-\\x08\\x0B\\x0C\\x0E-\\x1F]");
    string out = StrReplaceAll(clean, "\\", "\\\\");
    out = StrReplaceAll(out, "\"", "\\\"");
    out = StrReplaceAll(out, "\n", "\\n");
    out = StrReplaceAll(out, "\r", "\\r");
    out = StrReplaceAll(out, "\t", "\\t");
    return out;
}

string JStr(const string &in v)
{
    return "\"" + JsonEscape(v) + "\"";
}

string MaskKey(const string &in k)
{
    if (k.empty()) return "(未设置)";
    if (k.length() < 16) return "****";
    return k.Left(4) + "****" + k.Right(4);
}

// 日志里不能出现 Key（auth=query 时 Key 在 URL 中，且可能被 percent-encode）
string SafeUrl(const string &in url)
{
    if (g_key.empty()) return url;
    string out = StrReplaceAll(url, HostUrlEncode(g_key), "****");
    out = StrReplaceAll(out, g_key, "****");
    return out;
}

// 清洗数值参数：只保留数字与点，最多一个小数点
string NormalizeTemp(const string &in src)
{
    string cleaned = StripChars(src, "[^0-9.]");
    if (cleaned.empty() || cleaned == ".") return "0.2";
    array<string> parts = SplitStr(cleaned, ".");
    if (parts.size() > 2) return "0.2";
    return cleaned;
}

// HostRegExpRemove 只删第一个匹配；用于"删除所有匹配字符/片段"
string StripChars(const string &in src, const string &in pattern)
{
    string out = src;
    int guard = 0;
    while (guard < 1024)
    {
        string next = HostRegExpRemove(out, pattern);
        if (next == out) break;
        out = next;
        guard++;
    }
    return out;
}

void Dbg(const string &in msg)
{
    if (!g_debug) return;
    EnsureConsole();
    if (!g_pending_log.empty())
    {
        HostPrintUTF8("[AnyTranslate] " + g_pending_log + "\n");
        g_pending_log = "";
    }
    HostPrintUTF8("[AnyTranslate] " + msg + "\n");
}

void EnsureConsole()
{
    if (g_debug && !g_console_opened)
    {
        HostOpenConsole();
        g_console_opened = true;
    }
}

// ===========================================================================
// 配置读写
// ===========================================================================

string CurrentKey()
{
    if (!g_key.empty()) return g_key;
    return HostLoadString("anytr_key", "");
}

string DescribeCurrentSpec()
{
    string spec = g_spec;
    if (spec.empty()) spec = HostLoadString("anytr_spec", "");
    if (spec.empty()) spec = "(默认) " + DEFAULT_SPEC;
    return spec;
}

string DefaultPathFor(const string &in proto)
{
    if (proto == "openai") return "choices[0].message.content";
    if (proto == "anthropic") return "content";
    if (proto == "gemini") return "candidates[0].content.parts";
    if (proto == "ollama") return "message.content";
    return "";
}

int PresetIndex(const string &in provider)
{
    for (int i = 0; i < P_ID.size(); i++)
    {
        if (P_ID[i] == provider) return i;
    }
    return -1;
}

// 解析登录框 User 字段；成功返回空串，失败返回中文错误
// 语法: preset[:model][|opts]  或  custom|<endpoint>|<model>[|opts]
string ParseSpec(const string &in specIn)
{
    string spec = Trimmed(specIn);
    if (spec.empty()) spec = DEFAULT_SPEC;

    string provider = "";
    string model = "";
    string baseOverride = "";
    string optStr = "";
    string pathOpt = "";
    string authOpt = "";
    string keynameOpt = "";
    string bodyOpt = "";
    string tempOpt = "";
    string maxTokOpt = "";
    string probeOpt = "";
    string debugOpt = "";
    string versionOpt = "";
    string minimalOpt = "";
    bool isCustom = false;

    // ---- 拆出 endpoint / model / opts ----
    if (StartsWith(spec, "custom|"))
    {
        isCustom = true;
        string rest = spec.substr(7);
        int p2 = rest.findFirst("|", 0);
        if (p2 < 0)
        {
            baseOverride = Trimmed(rest);
        }
        else
        {
            baseOverride = Trimmed(rest.Left(p2));
            string rest2 = rest.substr(p2 + 1);
            int p3 = rest2.findFirst("|", 0);
            if (p3 < 0)
            {
                model = Trimmed(rest2);
            }
            else
            {
                model = Trimmed(rest2.Left(p3));
                optStr = rest2.substr(p3 + 1);
            }
        }
        provider = "custom";
        if (baseOverride.empty())
        {
            return "custom 缺少 url，应为 custom|<url>|<model>|[opts]";
        }
    }
    else
    {
        string head = spec;
        int bar = head.findFirst("|", 0);
        if (bar >= 0)
        {
            optStr = head.substr(bar + 1);
            head = head.Left(bar);
        }
        int c = head.findFirst(":", 0);
        if (c < 0)
        {
            provider = Trimmed(head);
        }
        else
        {
            provider = Trimmed(head.substr(0, c));
            model = Trimmed(head.substr(c + 1));
        }
    }

    // ---- opts: k=v;... ----
    array<string> kvs = SplitStr(optStr, ";");
    for (int i = 0; i < kvs.size(); i++)
    {
        string kv = Trimmed(kvs[i]);
        if (kv.empty()) continue;
        int eq = kv.findFirst("=", 0);
        if (eq <= 0) continue;
        string k = Trimmed(kv.substr(0, eq));
        string v = Trimmed(kv.substr(eq + 1));
        if (k == "path") pathOpt = v;
        else if (k == "auth") authOpt = v;
        else if (k == "keyname") keynameOpt = v;
        else if (k == "body") bodyOpt = v;
        else if (k == "temp") tempOpt = v;
        else if (k == "max_tokens") maxTokOpt = v;
        else if (k == "probe") probeOpt = v;
        else if (k == "debug") debugOpt = v;
        else if (k == "version") versionOpt = v;
        else if (k == "minimal") minimalOpt = v;
    }

    provider = provider.MakeLower();
    int idx = PresetIndex(provider);
    if (idx < 0)
    {
        return "未知服务商: " + provider + "。可用: openai/deepseek/moonshot/zhipu/qwen/siliconflow/openrouter/groq/xai/mistral/together/lmstudio/vllm/ollama/anthropic/gemini/custom";
    }

    string base = isCustom ? baseOverride : P_BASE[idx];
    string proto = isCustom ? "openai" : P_PROTO[idx];
    string auth = isCustom ? "bearer" : P_AUTH[idx];
    if (model.empty() && !isCustom) model = P_MODEL[idx];

    if (base.empty())
    {
        return "custom 需要完整 URL，例如 custom|https://host/v1/chat/completions|model";
    }
    if (base.length() > 1)
    {
        while (base.Right(1) == "/")
        {
            base = base.Left(base.length() - 1);
        }
    }

    if (!authOpt.empty()) auth = authOpt;
    if (auth != "bearer" && auth != "x-api-key" && auth != "query" && auth != "none")
    {
        return "auth 只能是 bearer / x-api-key / query / none";
    }

    string keyname = keynameOpt;
    if (keyname.empty()) keyname = P_KEYNAME[idx];
    if (keyname.empty())
    {
        if (auth == "bearer") keyname = "Authorization";
        else if (auth == "x-api-key") keyname = "x-api-key";
        else keyname = "key";
    }
    // auth=query 时参数名必须能作为 query key 使用；用户显式 keyname= 优先
    if (auth == "query" && keynameOpt.empty()) keyname = "key";

    string path = isCustom ? "" : DefaultPathFor(proto);
    if (!pathOpt.empty()) path = pathOpt;
    if (path.empty()) path = DefaultPathFor("openai");

    string probe = isCustom ? "none" : "models";
    if (!probeOpt.empty()) probe = probeOpt;

    string temperature = "0.2";
    if (!tempOpt.empty()) temperature = tempOpt;
    temperature = NormalizeTemp(temperature);

    string maxTokens = "";
    if (!maxTokOpt.empty()) maxTokens = StripChars(maxTokOpt, "[^0-9]");

    string debug = debugOpt.empty() ? "0" : debugOpt;
    string version = versionOpt.empty() ? "2023-06-01" : versionOpt;
    string extraBody = isCustom ? "" : P_EXTRA[idx];

    g_provider = provider;
    g_base = base;
    g_model = model;
    g_proto = proto;
    g_auth = auth;
    g_path = path;
    g_keyname = keyname;
    g_body_template = bodyOpt;
    g_temperature = temperature;
    g_max_tokens = maxTokens;
    g_probe = probe;
    g_debug = (debug == "1" || debug == "true");
    g_version = version;
    g_extra_body = extraBody;
    g_minimal_body = (minimalOpt == "1" || minimalOpt == "true");
    g_spec = spec;
    g_key = CurrentKey();
    return "";
}

// ===========================================================================
// 语言解析
// ===========================================================================

int LangIndex(const string &in label)
{
    for (int i = 0; i < L_LABEL.size(); i++)
    {
        if (L_LABEL[i] == label) return i;
    }
    return -1;
}

string ResolvePromptLang(const string &in label)
{
    int idx = LangIndex(label);
    if (idx >= 0) return L_PROMPT[idx];
    return label;
}

bool IsRtlLabel(const string &in label)
{
    int idx = LangIndex(label);
    if (idx < 0) return false;
    string code = L_CODE[idx];
    return (code == "ar" || code == "he" || code == "fa" || code == "ur");
}

// ===========================================================================
// 上下文与缓存
// ===========================================================================

void ClearContext()
{
    g_history.resize(0);
    g_cache_keys.resize(0);
    g_cache_vals.resize(0);
}

void PushHistory(const string &in text)
{
    g_history.insertLast(text);
    while (g_history.size() > MAX_HISTORY)
    {
        g_history.removeAt(0);
    }
}

string BuildHistoryText()
{
    string out = "";
    for (int i = 0; i < g_history.size(); i++)
    {
        if (!out.empty()) out += "\n";
        out += "- " + g_history[i];
    }
    return out;
}

int CacheFind(const string &in key)
{
    for (int i = 0; i < g_cache_keys.size(); i++)
    {
        if (g_cache_keys[i] == key) return i;
    }
    return -1;
}

void CachePut(const string &in key, const string &in val)
{
    int i = CacheFind(key);
    if (i >= 0)
    {
        g_cache_vals[i] = val;
        return;
    }
    if (g_cache_keys.size() >= CACHE_MAX)
    {
        g_cache_keys.removeAt(0);
        g_cache_vals.removeAt(0);
    }
    g_cache_keys.insertLast(key);
    g_cache_vals.insertLast(val);
}

// ===========================================================================
// 提示词
// ===========================================================================

string BuildPrompt(const string &in text, const string &in srcName, const string &in dstName)
{
    string prompt = "你是一个专业的影视字幕翻译引擎，只负责把字幕精准翻译成目标语言。\n";
    prompt += "任务：把【待翻译字幕】翻译成" + dstName + "。\n";
    if (!srcName.empty())
    {
        prompt += "字幕原文语言：" + srcName + "。\n";
    }
    prompt += "严格遵守以下规则：\n";
    prompt += "1. 只输出译文本身，不要任何解释、前言、注释、引号或 Markdown 标记。\n";
    prompt += "2. 保持与原文相同的行数与顺序，不合并、不拆分文本行。\n";
    prompt += "3. 保持原有标点与换行习惯，符合目标语言字幕的阅读习惯。\n";
    prompt += "4. 人名、专有名词、数字、符号如无必要保持不变，不要音译已有通用译名的名称。\n";
    prompt += "5. 不要输出思考过程，只给最终译文。\n";

    string history = BuildHistoryText();
    if (!history.empty())
    {
        prompt += "6. 严禁翻译【最近台词】部分，它只用于理解当前语境。\n\n";
        prompt += "【最近台词（仅供理解语境，不要翻译）】\n'''\n";
        prompt += history;
        prompt += "\n'''\n\n";
    }
    else
    {
        prompt += "\n";
    }

    prompt += "【待翻译字幕】\n'''\n";
    prompt += text;
    prompt += "\n'''";
    return prompt;
}

// ===========================================================================
// 请求体构造
// ===========================================================================

string ModelField()
{
    if (g_model.empty()) return "";
    return "\"model\":" + JStr(g_model) + ",";
}

string MessagesField(const string &in prompt)
{
    return "\"messages\":[{\"role\":\"user\",\"content\":" + JStr(prompt) + "}]";
}

string BuildBody(const string &in prompt, const string &in text,
                 const string &in srcName, const string &in dstName, bool minimal)
{
    if (g_provider == "custom" && !g_body_template.empty())
    {
        string tpl = g_body_template;
        tpl = StrReplaceAll(tpl, "{{prompt}}", JsonEscape(prompt));
        tpl = StrReplaceAll(tpl, "{{text}}", JsonEscape(text));
        tpl = StrReplaceAll(tpl, "{{model}}", JsonEscape(g_model));
        tpl = StrReplaceAll(tpl, "{{src}}", JsonEscape(srcName));
        tpl = StrReplaceAll(tpl, "{{dst}}", JsonEscape(dstName));
        return tpl;
    }

    if (g_proto == "anthropic")
    {
        string mt = g_max_tokens;
        if (mt.empty()) mt = "1024";
        return "{" + ModelField() + "\"max_tokens\":" + mt + "," + MessagesField(prompt) + "}";
    }
    if (g_proto == "gemini")
    {
        string cfg = "\"temperature\":" + g_temperature;
        if (!g_max_tokens.empty()) cfg += ",\"maxOutputTokens\":" + g_max_tokens;
        if (!minimal) cfg += ",\"thinkingConfig\":{\"thinkingBudget\":0}";
        return "{\"contents\":[{\"parts\":[{\"text\":" + JStr(prompt) + "}]}],\"generationConfig\":{" + cfg + "}}";
    }
    if (g_proto == "ollama")
    {
        string opts = "\"temperature\":" + g_temperature;
        if (!g_max_tokens.empty()) opts += ",\"num_predict\":" + g_max_tokens;
        string tail = "\"stream\":false";
        if (!minimal) tail = "\"stream\":false,\"think\":false,\"options\":{" + opts + "}";
        return "{" + ModelField() + MessagesField(prompt) + "," + tail + "}";
    }

    if (minimal)
    {
        return "{" + ModelField() + MessagesField(prompt) + ",\"stream\":false}";
    }

    string tail2 = "\"stream\":false,\"temperature\":" + g_temperature;
    if (!g_max_tokens.empty()) tail2 += ",\"max_completion_tokens\":" + g_max_tokens;
    return "{" + ModelField() + MessagesField(prompt) + "," + tail2 + g_extra_body + "}";
}

// auth=query 时把 Key 拼到 URL；BuildUrl 与 ProbeUrl 共用，避免两处参数名不一致
string AppendQueryAuth(const string &in urlIn)
{
    string url = urlIn;
    if (g_auth != "query" || g_key.empty()) return url;
    string sep = "?";
    if (url.findFirst("?", 0) >= 0) sep = "&";
    return url + sep + g_keyname + "=" + HostUrlEncode(g_key);
}

string BuildUrl()
{
    string url = g_base;
    if (g_provider != "custom")
    {
        if (g_proto == "openai") url = url + "/chat/completions";
        else if (g_proto == "anthropic") url = url + "/v1/messages";
        else if (g_proto == "gemini") url = url + "/v1beta/models/" + g_model + ":generateContent";
        else if (g_proto == "ollama") url = url + "/api/chat";
    }
    return AppendQueryAuth(url);
}

string BuildHeaders()
{
    string headers = "Content-Type: application/json\r\nAccept: application/json\r\n";
    if (g_auth == "bearer" && !g_key.empty())
    {
        headers += "Authorization: Bearer " + g_key + "\r\n";
    }
    else if (g_auth == "x-api-key" && !g_key.empty())
    {
        headers += g_keyname + ": " + g_key + "\r\n";
        if (g_proto == "anthropic") headers += "anthropic-version: " + g_version + "\r\n";
    }
    return headers;
}

// ===========================================================================
// JSON 路径解析
// ===========================================================================

int DigitToInt(const string &in s)
{
    array<string> digits = {"0", "1", "2", "3", "4", "5", "6", "7", "8", "9"};
    for (int i = 0; i < 10; i++)
    {
        if (s == digits[i]) return i;
    }
    return -1;
}

string NodeText(JsonValue node)
{
    if (node.isString()) return node.asString();
    if (node.isArray())
    {
        string out = "";
        for (int i = 0; i < node.size(); i++)
        {
            string t = NodeText(node[i]);
            if (!t.empty())
            {
                if (!out.empty()) out += "\n";
                out += t;
            }
        }
        return out;
    }
    if (node.isObject())
    {
        JsonValue thought = node["thought"];
        if (thought.isBool() && thought.asBool()) return "";
        JsonValue ntype = node["type"];
        if (ntype.isString())
        {
            string ts = ntype.asString();
            if (ts == "thinking" || ts == "redacted_thinking" || ts == "reasoning") return "";
        }
        JsonValue t = node["text"];
        if (t.isString()) return t.asString();
        JsonValue c = node["content"];
        if (c.isString()) return c.asString();
        if (c.isArray() || c.isObject()) return NodeText(c);
        return "";
    }
    return "";
}

string WalkPath(JsonValue node, array<string> tokens, int depth)
{
    if (depth >= tokens.size()) return NodeText(node);
    string tok = tokens[depth];
    int br = tok.findFirst("[", 0);
    if (br >= 0)
    {
        string name = tok.substr(0, br);
        string idxStr = tok.substr(br + 1, tok.length() - br - 2);
        int idx = DigitToInt(idxStr);
        if (idx < 0) return "";
        if (name.empty())
        {
            if (!node.isArray() || idx >= node.size()) return "";
            return WalkPath(node[idx], tokens, depth + 1);
        }
        if (!node.isObject()) return "";
        JsonValue child = node[name];
        if (!child.isArray() || idx >= child.size()) return "";
        return WalkPath(child[idx], tokens, depth + 1);
    }
    if (!node.isObject()) return "";
    JsonValue next = node[tok];
    return WalkPath(next, tokens, depth + 1);
}

string ExtractByPath(JsonValue root, const string &in path)
{
    g_path_found = false;
    if (path.empty()) return "";
    array<string> tokens = SplitStr(path, ".");
    if (tokens.size() == 0) return "";
    string v = WalkPath(root, tokens, 0);
    if (!v.empty()) g_path_found = true;
    return v;
}

// ===========================================================================
// 模型列表 / 登录自检
// ===========================================================================

array<string> ParseModelArray(JsonValue arr)
{
    array<string> out;
    if (!arr.isArray()) return out;
    for (int i = 0; i < arr.size(); i++)
    {
        JsonValue item = arr[i];
        if (item.isString())
        {
            out.insertLast(item.asString());
            continue;
        }
        if (!item.isObject()) continue;
        JsonValue id = item["id"];
        if (id.isString())
        {
            out.insertLast(id.asString());
            continue;
        }
        JsonValue nm = item["name"];
        if (nm.isString())
        {
            string n = StrReplaceAll(nm.asString(), "models/", "");
            out.insertLast(n);
        }
    }
    return out;
}

array<string> ParseModels(const string &in content)
{
    array<string> out;
    JsonReader reader;
    JsonValue root;
    if (!reader.parse(content, root)) return out;
    if (root.isArray()) return ParseModelArray(root);
    if (!root.isObject()) return out;

    JsonValue data = root["data"];
    if (data.isArray()) return ParseModelArray(data);
    JsonValue models = root["models"];
    if (models.isArray()) return ParseModelArray(models);
    return out;
}

bool ModelMatched(array<string> models, const string &in model)
{
    string want = model;
    want = want.MakeLower();
    for (int i = 0; i < models.size(); i++)
    {
        string have = models[i];
        have = have.MakeLower();
        if (have == want) return true;
        if (have.findFirst(want + ":", 0) == 0) return true;
    }
    return false;
}

string JoinModels(array<string> models, int maxCount)
{
    string out = "";
    int n = models.size();
    if (n > maxCount) n = maxCount;
    for (int i = 0; i < n; i++)
    {
        if (!out.empty()) out += ", ";
        out += models[i];
    }
    if (models.size() > maxCount) out += " ...";
    return out;
}

string ProbeUrl()
{
    string url = "";
    if (g_proto == "openai") url = g_base + "/models";
    else if (g_proto == "ollama") url = g_base + "/api/tags";
    else if (g_proto == "anthropic") url = g_base + "/v1/models";
    else if (g_proto == "gemini") url = g_base + "/v1beta/models";
    else return "";
    return AppendQueryAuth(url);
}

string Probe()
{
    if (g_probe == "none") return "";
    if (g_provider == "custom") return "";
    string url = ProbeUrl();
    if (url.empty()) return "";

    HostIncTimeOut(15000);
    uintptr http = HostOpenHTTP(url, USER_AGENT, BuildHeaders(), "", true);
    if (http == 0)
    {
        return "无法连接 " + g_base + "（检查地址、端口、网络或代理）";
    }
    int status = HostGetStatusHTTP(http);
    string content = HostGetContentHTTP(http);
    HostCloseHTTP(http);

    if (status == 401 || status == 403)
    {
        return "API Key 无效或无权限（HTTP " + formatInt(status) + "）";
    }
    if (status == 402)
    {
        return "账户余额不足（HTTP 402），请充值后再试";
    }
    if (status == 404 || status == 405)
    {
        // 预设的 base URL 由插件提供，404/405 通常表示该服务没有实现 /models；
        // 放行登录，把模型名问题留给实际翻译请求（可用 debug=1 观察）
        Dbg("probe unsupported (HTTP " + formatInt(status) + "): " + g_base);
        return "";
    }
    if (status == 413)
    {
        return "请求体过大（HTTP 413）";
    }
    if (status == 422)
    {
        return "参数非法（HTTP 422）: " + Truncate(content, 160);
    }
    if (status == 429)
    {
        return "请求过于频繁（HTTP 429），请稍后重试";
    }
    if (status >= 500)
    {
        return "服务端错误（HTTP " + formatInt(status) + "），请稍后重试";
    }
    if (status < 200 || status >= 300)
    {
        return "登录自检失败（HTTP " + formatInt(status) + "）: " + Truncate(content, 200);
    }

    array<string> models = ParseModels(content);
    if (!g_model.empty() && models.size() > 0 && !ModelMatched(models, g_model))
    {
        return "未找到模型: " + g_model + "；可用示例: " + JoinModels(models, 6);
    }
    return "";
}

// ===========================================================================
// 文本清洗
// ===========================================================================

string StripKnownPrefixes(const string &in raw)
{
    string s = raw;
    array<string> prefixes =
    {
        "翻译：", "翻译:", "译文：", "译文:", "譯文：", "譯文:",
        "Translation:", "translation:", "Translated text:", "Translation :",
        "Answer:", "输出：", "输出:", "【译文】"
    };
    for (int round = 0; round < 3; round++)
    {
        bool removed = false;
        for (int i = 0; i < prefixes.size(); i++)
        {
            if (StartsWith(s, prefixes[i]))
            {
                s = s.substr(prefixes[i].length());
                s = s.Trim();
                removed = true;
                break;
            }
        }
        if (!removed) break;
    }

    if (StartsWith(s, "原文：") || StartsWith(s, "原文:") || StartsWith(s, "Original:"))
    {
        int nl = s.findFirst("\n", 0);
        if (nl >= 0)
        {
            s = s.substr(nl + 1);
            s = s.Trim();
        }
    }
    return s;
}

string CleanTranslation(const string &in raw, bool rtl)
{
    string s = raw;
    s = s.Trim();

    if (StartsWith(s, "```"))
    {
        int nl = s.findFirst("\n", 0);
        if (nl >= 0) s = s.substr(nl + 1);
    }
    if (s.length() >= 3 && s.Right(3) == "```")
    {
        s = s.Left(s.length() - 3);
    }
    s = s.Trim();

    s = StripKnownPrefixes(s);
    s = s.Trim();

    if (s.length() >= 2)
    {
        string first = s.Left(1);
        string last = s.Right(1);
        if ((first == "\"" && last == "\"") ||
            (first == "“" && last == "”") ||
            (first == "「" && last == "」") ||
            (first == "『" && last == "』"))
        {
            s = s.substr(1, s.length() - 2);
            s = s.Trim();
        }
    }

    s = StrReplaceAll(s, "\r\n", "\n");
    s = StrReplaceAll(s, "\r", "\n");
    s = StrReplaceAll(s, "<br/>", "\n");
    s = StrReplaceAll(s, "<br />", "\n");
    s = StrReplaceAll(s, "<br>", "\n");
    s = StrReplaceAll(s, "\n\n\n", "\n\n");

    if (rtl) s = "\u202B" + s;
    return s.Trim();
}

// ===========================================================================
// HTTP 发送
// ===========================================================================

bool SendOnce(const string &in url, const string &in headers, const string &in body, string &out text)
{
    text = "";
    HostIncTimeOut(20000);

    uintptr http = HostOpenHTTP(url, USER_AGENT, headers, body, true);
    if (http == 0)
    {
        g_http_status = 0;
        Dbg("network error: " + SafeUrl(url));
        return false;
    }
    int status = HostGetStatusHTTP(http);
    string content = HostGetContentHTTP(http);
    HostCloseHTTP(http);

    g_http_status = status;
    g_http_body = content;

    Dbg("HTTP " + formatInt(status) + " <- " + Truncate(content, 500));

    if (status < 200 || status >= 300) return false;

    JsonReader reader;
    JsonValue root;
    if (!reader.parse(content, root))
    {
        Dbg("json parse failed");
        return false;
    }

    string v = ExtractByPath(root, g_path);
    if (!g_path_found || v.empty())
    {
        Dbg("path not found or empty: " + g_path);
        return false;
    }

    string cleaned = CleanTranslation(v, g_dst_rtl);
    if (cleaned.empty()) return false;
    text = cleaned;
    return true;
}

string ErrorHint()
{
    int status = g_http_status;
    if (status == 0) return "网络不可达";
    if (status == 401 || status == 403) return "API Key 无效或无权限";
    if (status == 402) return "余额不足";
    if (status == 404) return "接口地址或模型不存在";
    if (status == 413) return "请求体过大";
    if (status == 422) return "参数非法";
    if (status == 429) return "请求过于频繁";
    if (status >= 500) return "服务端错误";
    if (status == 400) return "请求参数被拒绝";
    if (status > 0) return "HTTP " + formatInt(status);
    return "未知错误";
}

string ExtractErrorDetail()
{
    JsonReader reader;
    JsonValue root;
    if (!reader.parse(g_http_body, root) || !root.isObject()) return "";
    JsonValue err = root["error"];
    if (err.isString()) return err.asString();
    if (err.isObject())
    {
        JsonValue msg = err["message"];
        if (msg.isString()) return msg.asString();
    }
    JsonValue msg2 = root["message"];
    if (msg2.isString()) return msg2.asString();
    return "";
}

// ===========================================================================
// 翻译主流程
// ===========================================================================

string Translate(string Text, string &in SrcLang, string &in DstLang)
{
    string raw = Text;
    if (Trimmed(raw).empty()) return "";

    if (!g_configured)
    {
        string key = HostLoadString("anytr_key", "");
        string spec = HostLoadString("anytr_spec", "");
        if (spec.empty()) spec = DEFAULT_SPEC;
        string err = ParseSpec(spec);
        if (!err.empty())
        {
            g_last_error = err;
            g_logged_out = true;
        }
        g_key = key;
        g_configured = true;
    }
    if (g_logged_out) return "";
    if (g_base.empty()) return "";

    // 个别情况下 PotPlayer 会把上次写回的 "UTF8" 再传回来，用上次目标语言兜底
    string dstLabel = DstLang;
    if ((dstLabel.empty() || dstLabel == "UTF8") && !g_last_dst.empty()) dstLabel = g_last_dst;
    if (dstLabel == "UTF8") return "";
    if (dstLabel.empty() || dstLabel == "Auto" || dstLabel == "自动检测") return "";

    // 长时间暂停后重置上下文，避免不同片段串味
    uint now = HostGetTickCount();
    if (g_last_tick > uint(0) && (now - g_last_tick) > uint(120000))
    {
        ClearContext();
        Dbg("context reset after pause");
    }
    g_last_tick = now;
    g_last_dst = dstLabel;

    string ctxKey = g_provider + "|" + g_model + "|" + dstLabel;
    if (ctxKey != g_last_key)
    {
        ClearContext();
        g_last_key = ctxKey;
    }

    int hit = CacheFind(raw);
    if (hit >= 0)
    {
        SrcLang = "UTF8";
        DstLang = "UTF8";
        return g_cache_vals[hit];
    }

    g_dst_rtl = IsRtlLabel(dstLabel);
    string srcName = "";
    if (!SrcLang.empty() && SrcLang != "自动检测" && SrcLang != "Auto" && SrcLang != "UTF8")
    {
        srcName = ResolvePromptLang(SrcLang);
    }
    string dstName = ResolvePromptLang(dstLabel);
    string prompt = BuildPrompt(raw, srcName, dstName);

    Dbg("translate: " + Truncate(raw, 80));

    string url = BuildUrl();
    string headers = BuildHeaders();
    string body = BuildBody(prompt, raw, srcName, dstName, g_minimal_body);
    Dbg("POST " + SafeUrl(url) + " body=" + Truncate(body, 500));

    uint startTick = HostGetTickCount();
    string result = "";
    string lastSentBody = body;
    bool ok = SendOnce(url, headers, body, result);
    int requests = 1;

    if (!ok && g_http_status == 400 && !g_minimal_body)
    {
        Dbg("400 detail: " + Truncate(ExtractErrorDetail(), 200));
        string minimalBody = BuildBody(prompt, raw, srcName, dstName, true);
        if (minimalBody != lastSentBody)
        {
            ok = SendOnce(url, headers, minimalBody, result);
            lastSentBody = minimalBody;
            requests++;
            if (ok)
            {
                g_minimal_body = true;
                Dbg("switch to minimal body after 400");
            }
        }
    }

    if (!ok && g_http_status == 200)
    {
        string minimalBody2 = BuildBody(prompt, raw, srcName, dstName, true);
        if (minimalBody2 != lastSentBody)
        {
            Dbg("empty content, retry minimal body");
            ok = SendOnce(url, headers, minimalBody2, result);
            lastSentBody = minimalBody2;
            requests++;
        }
    }

    if (!ok && (g_http_status == 429 || g_http_status >= 500))
    {
        HostSleep(400);
        ok = SendOnce(url, headers, body, result);
        requests++;
    }

    uint elapsed = HostGetTickCount() - startTick;
    if (!ok)
    {
        g_fail_count++;
        Dbg("translate failed in " + formatInt(int(elapsed)) + "ms, requests=" + formatInt(requests) + ": " + ErrorHint());
        if (g_fail_count >= FAIL_CLEAR)
        {
            g_fail_count = 0;
            ClearContext();
        }
        return "";
    }

    g_fail_count = 0;
    CachePut(raw, result);
    PushHistory(raw);
    Dbg("translate ok in " + formatInt(int(elapsed)) + "ms, requests=" + formatInt(requests));

    SrcLang = "UTF8";
    DstLang = "UTF8";
    return result;
}

// ===========================================================================
// 登录 / 初始化 / 语言列表
// ===========================================================================

string ServerLogin(string User, string Pass)
{
    string spec = Trimmed(User);
    string key = Trimmed(Pass);

    if (spec.empty()) spec = HostLoadString("anytr_spec", "");
    if (spec.empty()) spec = DEFAULT_SPEC;
    if (key.empty()) key = HostLoadString("anytr_key", "");

    string err = ParseSpec(spec);
    if (!err.empty())
    {
        // 语法错误：旧配置仍可用，只在登录框提示错误摘要
        g_last_error = err;
        return err;
    }

    g_key = key;
    g_spec = spec;

    // custom 允许无 Key（可能是 auth=none 的本机服务）；预设按协议要求 Key
    if (g_auth != "none" && g_key.empty() && g_provider != "custom")
    {
        // 登录失败时禁用运行期翻译，避免用未验证的配置逐行请求
        g_logged_out = true;
        g_last_error = "缺少 API Key";
        return "请在密码框填写 API Key（本机服务可把 auth 设为 none）";
    }
    if (g_model.empty() && (g_proto == "anthropic" || g_proto == "gemini"))
    {
        g_logged_out = true;
        g_last_error = "缺少模型名";
        return "该服务必须指定模型名，例如 " + g_provider + ":<model>";
    }

    string probeErr = Probe();
    if (!probeErr.empty())
    {
        g_logged_out = true;
        g_last_error = probeErr;
        return probeErr;
    }

    g_configured = true;
    g_logged_out = false;
    g_last_error = "";
    HostSaveString("anytr_spec", spec);
    HostSaveString("anytr_key", g_key);
    ClearContext();

    Dbg("login ok: " + SafeUrl(spec));
    return "200 ok";
}

void ServerLogout()
{
    g_key = "";
    g_configured = false;
    g_logged_out = true;
    g_spec = "";
    g_base = "";
    g_provider = "";
    g_last_error = "";
    g_last_dst = "";
    HostSaveString("anytr_key", "");
    HostSaveString("anytr_spec", "");
    ClearContext();
}

void OnInitialize()
{
    string key = HostLoadString("anytr_key", "");
    string spec = HostLoadString("anytr_spec", "");
    if (spec.empty()) spec = DEFAULT_SPEC;
    string err = ParseSpec(spec);
    g_key = key;
    g_configured = true;
    if (err.empty())
    {
        g_logged_out = false;
        g_last_error = "";
    }
    else
    {
        // 保存的 spec 非法：禁用翻译并在登录框提示，等待用户重新配置
        g_logged_out = true;
        g_last_error = err;
    }
    // 启动阶段不弹控制台：日志挂起，等首次登录/翻译时再输出
    g_pending_log = "init: " + SafeUrl(spec) + " err=" + err;
}

void OnFinalize()
{
    ClearContext();
}

array<string> GetSrcLangs()
{
    array<string> ret;
    ret.insertLast("自动检测");
    for (int i = 0; i < L_LABEL.size(); i++)
    {
        ret.insertLast(L_LABEL[i]);
    }
    return ret;
}

array<string> GetDstLangs()
{
    array<string> ret;
    for (int i = 0; i < L_LABEL.size(); i++)
    {
        ret.insertLast(L_LABEL[i]);
    }
    return ret;
}
