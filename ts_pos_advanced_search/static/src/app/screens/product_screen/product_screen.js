import { ProductScreen } from "@point_of_sale/app/screens/product_screen/product_screen";
import { unaccent } from "@web/core/utils/strings";
import { patch } from "@web/core/utils/patch";

patch(ProductScreen.prototype, {
    // @override
    getProductsBySearchWord(searchWord) {
        const words = unaccent(searchWord.toLowerCase(), false);
        const products = this.pos.selectedCategory?.id
            ? this.getProductsByCategory(this.pos.selectedCategory)
            : this.products;
        // const filteredProducts = products.filter((p) => unaccent(p.searchString).includes(words));
        const filteredProducts = products.filter((p) => {
            // Normalize the product search string by removing accents
            const normalizedSearchString = unaccent(p.searchString).toLowerCase();
            // Split the search query into individual words and normalize each word
            const queryWords = words.toLowerCase().split(/\s+/).filter(Boolean); // Split by spaces and remove empty strings
            // Check if all the query words are substrings of the product's normalized search string
            return queryWords.every((word) => normalizedSearchString.includes(word));
        });
        return filteredProducts.sort((a, b) => {
            const nameA = unaccent(a.searchString);
            const nameB = unaccent(b.searchString);
            // Sort by match index, push non-matching items to the end, and use alphabetical order as a tiebreaker
            return nameA.indexOf(words) - nameB.indexOf(words) || nameA.localeCompare(nameB);
        });
    }
});
