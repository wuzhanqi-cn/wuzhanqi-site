/**
 * wuzhanqi.cn 留言板后端
 * Cloudflare Pages Function — POST /api/message
 *
 * 流程：前端 POST → 本函数 → Resend API → QQ 邮箱
 *
 * 需在 Cloudflare Pages → Settings → Environment variables 中设置：
 *   - RESEND_API_KEY    : Resend 控制台生成的 API Key (re_xxx...)
 *
 * 可选环境变量：
 *   - RESEND_FROM       : 发件人邮箱 (默认 onboarding@resend.dev)
 *                         改成自己的域名邮箱需先在 Resend 验证域名
 *   - MAIL_TO           : 收件邮箱 (默认 181609798@qq.com)
 */

// 简单内存级限流（每个 Pages 实例独立，重启失效，仅防脚本小子滥用）
const rateMap = new Map();
const RATE_LIMIT_WINDOW = 60_000; // 60 秒
const RATE_LIMIT_MAX = 3;         // 60 秒内最多 3 条

function getClientId(req) {
    // 优先用 CF 提供的 IP，否则回退到 remote addr（Pages 会有 cf-connecting-ip）
    return req.headers.get('cf-connecting-ip')
        || req.headers.get('x-forwarded-for')?.split(',')[0]?.trim()
        || 'unknown';
}

function checkRate(ip) {
    const now = Date.now();
    const arr = rateMap.get(ip) || [];
    // 清理过期
    const fresh = arr.filter(t => now - t < RATE_LIMIT_WINDOW);
    if (fresh.length >= RATE_LIMIT_MAX) return false;
    fresh.push(now);
    rateMap.set(ip, fresh);
    return true;
}

function escapeHtml(s) {
    if (typeof s !== 'string') return '';
    return s.replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    })[c]);
}

function corsHeaders() {
    return {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'POST, OPTIONS',
        'Access-Control-Allow-Headers': 'Content-Type',
    };
}

export async function onRequestOptions() {
    return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function onRequestPost(context) {
    const { request, env } = context;

    try {
        const ct = request.headers.get('Content-Type') || '';
        if (!ct.includes('application/json')) {
            return json({ error: 'Content-Type 必须是 application/json' }, 400);
        }

        const body = await request.json().catch(() => null);
        if (!body || typeof body !== 'object') {
            return json({ error: '请求体不是合法 JSON' }, 400);
        }

        const nickname = String(body.nickname || '').trim().slice(0, 50);
        const content  = String(body.content  || '').trim().slice(0, 4000);
        const attachments = Array.isArray(body.attachments) ? body.attachments.slice(0, 20) : [];
        const htmlImages = typeof body.html_images === 'string' ? body.html_images.slice(0, 200000) : '';
        const meta = body.meta && typeof body.meta === 'object' ? body.meta : {};

        // ===== 校验 =====
        if (!nickname) return json({ error: '请输入昵称' }, 400);
        if (!content && attachments.length === 0) return json({ error: '请输入留言或添加附件' }, 400);

        // 单条附件大小限制（防爆，Resend 限制 40MB 总）
        for (const a of attachments) {
            if (!a || typeof a.name !== 'string' || a.name.length > 200) {
                return json({ error: '附件名无效' }, 400);
            }
            if (typeof a.size !== 'number' || a.size < 0 || a.size > 5 * 1024 * 1024) {
                return json({ error: '单个附件不能超过 5MB' }, 400);
            }
        }

        // ===== 限流 =====
        const ip = getClientId(request);
        if (!checkRate(ip)) {
            return json({ error: '留言太频繁，请稍后再试（60 秒内最多 3 条）' }, 429);
        }

        // ===== 构建邮件 =====
        const apiKey  = env.RESEND_API_KEY;
        const from    = env.RESEND_FROM    || 'wuzhanqi留言板 <onboarding@resend.dev>';
        const to      = env.MAIL_TO        || '181609798@qq.com';

        if (!apiKey) {
            console.error('RESEND_API_KEY 未配置');
            return json({ error: '服务端邮件密钥未配置，请联系站长' }, 500);
        }

        const now = new Date().toLocaleString('zh-CN', {
            timeZone: 'Asia/Shanghai',
            hour12: false,
        });

        // 纯文本版本
        let textBody = content || '(无文字内容)';
        if (attachments.length > 0) {
            textBody += '\n\n📎 附件列表:';
            attachments.forEach((a, i) => {
                const sizeStr = a.size < 1024
                    ? a.size + 'B'
                    : (a.size / 1024).toFixed(1) + 'KB';
                textBody += `\n  ${i + 1}. ${a.name} (${sizeStr})`;
            });
        }
        textBody += `\n\n---\nIP: ${escapeHtml(meta.ip || ip)}\n时间: ${now}\n来源: ${escapeHtml(meta.url || '')}`;

        // HTML 版本
        const safeNick = escapeHtml(nickname);
        const safeContent = escapeHtml(content || '(无文字内容)');
        const safeUrl = escapeHtml(meta.url || '');

        const attachmentsHtml = attachments.length > 0
            ? `<tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;">附件</td><td style="padding:10px;">${
                attachments.map((a, i) => {
                    const sizeStr = a.size < 1024
                        ? a.size + 'B'
                        : (a.size / 1024).toFixed(1) + 'KB';
                    return `${i + 1}. ${escapeHtml(a.name)} (${sizeStr})`;
                }).join('<br>')
              }</td></tr>`
            : '';

        const htmlBody = `
<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#fafafa;font-family:'Microsoft YaHei','PingFang SC',sans-serif;">
<div style="max-width:600px;margin:0 auto;padding:20px;">
  <h2 style="color:#1976d2;margin:0 0 16px 0;">💬 wuzhanqi.cn 新留言</h2>
  <table style="width:100%;border-collapse:collapse;border:1px solid #e0e0e0;border-radius:8px;overflow:hidden;">
    <tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;width:80px;border-bottom:1px solid #e0e0e0;">昵称</td><td style="padding:10px;border-bottom:1px solid #e0e0e0;">${safeNick}</td></tr>
    <tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;border-bottom:1px solid #e0e0e0;vertical-align:top;">留言</td><td style="padding:10px;white-space:pre-wrap;border-bottom:1px solid #e0e0e0;">${safeContent}</td></tr>
    ${attachmentsHtml ? `${attachmentsHtml.replace('<tr>', '<tr style="border-bottom:1px solid #e0e0e0;">').replace('<td style="padding:10px;background:#f5f5f5;font-weight:bold;">附件</td>', '<td style="padding:10px;background:#f5f5f5;font-weight:bold;border-bottom:1px solid #e0e0e0;">附件</td>')}` : ''}
    <tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;border-bottom:1px solid #e0e0e0;">IP</td><td style="padding:10px;border-bottom:1px solid #e0e0e0;">${escapeHtml(meta.ip || ip)}</td></tr>
    <tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;border-bottom:1px solid #e0e0e0;">时间</td><td style="padding:10px;border-bottom:1px solid #e0e0e0;">${now}</td></tr>
    <tr><td style="padding:10px;background:#f5f5f5;font-weight:bold;">来源</td><td style="padding:10px;"><a href="${safeUrl}" style="color:#1976d2;">${safeUrl}</a></td></tr>
  </table>
  ${htmlImages}
  <p style="color:#999;font-size:12px;margin-top:20px;">本邮件由 wuzhanqi.cn 留言板自动发出，回复给留言者请用留言时填写的联系方式。</p>
</div>
</body></html>`.trim();

        // ===== 调 Resend API =====
        const resendRes = await fetch('https://api.resend.com/emails', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${apiKey}`,
                'Content-Type':  'application/json',
            },
            body: JSON.stringify({
                from,
                to: [to],
                subject: `💬 留言：${nickname} - wuzhanqi.cn`,
                text: textBody,
                html: htmlBody,
                reply_to: meta.replyTo && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(meta.replyTo)
                    ? meta.replyTo
                    : undefined,
            }),
        });

        const resendText = await resendRes.text();
        let resendData;
        try { resendData = JSON.parse(resendText); }
        catch { resendData = { raw: resendText }; }

        if (!resendRes.ok) {
            console.error('Resend 错误:', resendRes.status, resendData);
            return json({
                error: '邮件服务商返回错误，请稍后再试',
                detail: resendData?.message || resendData?.error?.message || resendText.slice(0, 200),
            }, 502);
        }

        return json({
            ok: true,
            id: resendData?.id,
            message: '留言已送达',
        }, 200);

    } catch (e) {
        console.error('留言处理异常:', e);
        return json({ error: '服务器异常', detail: String(e?.message || e) }, 500);
    }
}

function json(obj, status = 200) {
    return new Response(JSON.stringify(obj), {
        status,
        headers: {
            'Content-Type': 'application/json',
            ...corsHeaders(),
        },
    });
}