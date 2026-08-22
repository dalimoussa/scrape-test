/**
 * Classify a raw WebSocket frame by inspecting topic patterns and current page URL.
 * \x14OVInPlay_… / \x14OVS1  → 'live'
 * \x14OVM... / \x14OVD... / \x14OVC... / \x14OVPreMatch... → 'prematch'
 * Page URL #/IP/ → 'live'
 * Page URL #/AC/ (coupons), #/AS/ (sports), #/HO/ (home) → 'prematch'
 */
function classifyFrame(data) {
    if (typeof data !== 'string' || data.length < 2) return 'unknown';

    // 1. Explicit Live Topics
    if (data.indexOf('\x14OVInPlay') !== -1 || data.indexOf('\x14OVS1') !== -1) {
        return 'live';
    }

    // 2. Explicit Pre-Match & Coupon Topics
    if (data.indexOf('\x14OVM') !== -1 || 
        data.indexOf('\x14OVD') !== -1 || 
        data.indexOf('\x14OVC') !== -1 || 
        data.indexOf('\x14OVPreMatch') !== -1 || 
        data.indexOf('\x14OVUpcoming') !== -1) {
        return 'prematch';
    }

    // 3. Browser URL / Hash Navigation Context
    try {
        var hash = (window.location.hash || '').toUpperCase();
        var path = (window.location.pathname || '').toUpperCase();
        if (hash.indexOf('/IP') !== -1 || path.indexOf('/IN-PLAY') !== -1) {
            return 'live';
        }
        if (hash.indexOf('/AC') !== -1 || hash.indexOf('/AS') !== -1 || hash.indexOf('/HO') !== -1 || hash.indexOf('/AM') !== -1) {
            return 'prematch';
        }
    } catch(e) {}

    // 4. Live score and timer markers in payload
    if (data.indexOf('SS=') !== -1 && (data.indexOf('TM=') !== -1 || data.indexOf('TT=') !== -1)) {
        return 'live';
    }

    // 5. Delta category suffix patterns
    if (data.charCodeAt(0) === 0x15) {
        var m = data.match(/C\d+A_\d+_(\d)/);
        if (m) {
            return m[1] === '1' ? 'prematch' : 'live';
        }
    }

    return 'prematch';
}


function wrap(obj, meth) {
   var orig = obj[meth];
   obj[meth] = function wrapper() {
       var lang = null;
       try {
           if (window.GamingContext && window.GamingContext.languageId != null) {
               lang = window.GamingContext.languageId;
           }
       } catch (e) {}
       var frameType = classifyFrame(arguments[0]);
       window.dispatchEvent(new CustomEvent('sendToAPI', {
           detail: { data: arguments[0], lang: lang, type: frameType }
       }));
       return orig.apply(this, arguments);
   }
}

function hookSocket(){
    if(window.readit){
        wrap(window.readit.WebsocketTransportMethod.prototype, 'socketDataCallback');
    }
    else {
        setTimeout(hookSocket, 1000);
    }
}

setTimeout(hookSocket, 1000);
